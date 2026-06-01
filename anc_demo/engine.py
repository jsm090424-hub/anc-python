import time
import threading
import queue
import numpy as np
from dataclasses import dataclass, field
from typing import Callable, Optional, List
from .dsp import apply_hann_window, compute_fft, compute_ifft, calculate_db, magnitude_db, get_peak_frequency

try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False

@dataclass
class AncParams:
    anti_noise_gain: float = 0.6
    low_freq_hz: float = 50.0
    high_freq_hz: float = 1200.0

@dataclass
class AncSnapshot:
    input_db: float = -120.0
    output_db: float = -120.0
    residual_db: float = -120.0
    processing_time_ms: float = 0.0
    peak_frequency_hz: float = 0.0
    output_peak_frequency_hz: float = 0.0
    input_spectrum_db: np.ndarray = field(default_factory=lambda: np.zeros(512))
    output_spectrum_db: np.ndarray = field(default_factory=lambda: np.zeros(512))
    residual_history_db: List[float] = field(default_factory=list)

class AncEngine:
    def __init__(self, sample_rate: int = 48000, fft_size: int = 1024, ui_fps: int = 20, history_size: int = 100):
        self.sample_rate = sample_rate
        self.fft_size = fft_size
        self.ui_fps = ui_fps
        self.history_size = history_size
        
        self.running = False
        self.is_simulated = False
        self.params = AncParams()
        self.residual_history = []
        
        self.stream: Optional[Any] = None
        self.worker_thread: Optional[threading.Thread] = None
        self.on_snapshot_callback: Optional[Callable[[AncSnapshot], None]] = None
        
        # UI 업데이트 스로틀링을 위한 주기 관리
        self.last_snapshot_time = 0.0
        self.snapshot_interval = 1.0 / ui_fps

    def update_params(self, anti_noise_gain: float, low_freq_hz: float, high_freq_hz: float):
        self.params = AncParams(
            anti_noise_gain=anti_noise_gain,
            low_freq_hz=low_freq_hz,
            high_freq_hz=high_freq_hz
        )

    def start(self, on_snapshot: Callable[[AncSnapshot], None]) -> tuple[bool, str]:
        """오디오 엔진을 시작합니다.
        실제 오디오 기기 접근에 성공하면 True, 장치 부재로 시뮬레이션 모드로 Fallback 하면 (False, "시뮬레이션 모드 시작")을 반환합니다.
        """
        if self.running:
            return not self.is_simulated, "이미 실행 중입니다."

        self.on_snapshot_callback = on_snapshot
        self.running = True
        self.residual_history = []

        # 1. 실제 기기 기동 시도
        if SOUNDDEVICE_AVAILABLE:
            try:
                # 양방향 오디오 스트림 시동 (입력 채널 1, 출력 채널 1)
                self.stream = sd.Stream(
                    samplerate=self.sample_rate,
                    blocksize=self.fft_size,
                    channels=1,
                    dtype='float32',
                    callback=self._audio_callback
                )
                self.stream.start()
                self.is_simulated = False
                return True, "실제 오디오 기기가 연결되었습니다."
            except Exception as e:
                # 기기 시작 실패 시 Fallback
                self.stream = None
                # 아래 백그라운드 시뮬레이션 스레드 실행

        # 2. 시뮬레이션 모드로 진입
        self.is_simulated = True
        self.worker_thread = threading.Thread(target=self._simulation_loop, daemon=True)
        self.worker_thread.start()
        return False, "오디오 장치를 찾을 수 없어 가상 시뮬레이션 모드로 실행됩니다."

    def stop(self):
        self.running = False
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        
        if self.worker_thread:
            self.worker_thread.join(timeout=0.5)
            self.worker_thread = None

    def is_running(self) -> bool:
        return self.running

    def _process_frame(self, input_signal: np.ndarray) -> tuple[np.ndarray, AncSnapshot]:
        """주어진 입력 신호 프레임에 대해 FFT/IFFT 기반 ANC 신호 처리를 수행하고 Snapshot을 반환합니다."""
        start_time = time.perf_counter()
        
        # 1. Hann 윈도우 적용
        windowed_in = apply_hann_window(input_signal)
        
        # 2. FFT 수행
        spectrum = compute_fft(windowed_in)
        
        # 3. ANC 영역 계산 및 반대파 주파수 스펙트럼 복합
        low_bin = int((self.params.low_freq_hz / self.sample_rate) * self.fft_size)
        low_bin = max(0, min(low_bin, self.fft_size // 2))
        high_bin = int((self.params.high_freq_hz / self.sample_rate) * self.fft_size)
        high_bin = max(low_bin, min(high_bin, self.fft_size // 2))
        
        output_spectrum = np.zeros_like(spectrum, dtype=complex)
        
        for k in range(self.fft_size // 2):
            if low_bin <= k <= high_bin:
                output_spectrum[k] = -spectrum[k] * self.params.anti_noise_gain
                if k != 0:
                    mirror = self.fft_size - k
                    output_spectrum[mirror] = -spectrum[mirror] * self.params.anti_noise_gain
        
        # 4. 스펙트럼 분석 지표 획득
        input_spec_db = magnitude_db(spectrum)
        output_spec_db = magnitude_db(output_spectrum)
        
        peak_hz = get_peak_frequency(spectrum, self.sample_rate)
        out_peak_hz = get_peak_frequency(output_spectrum, self.sample_rate)
        
        # 5. IFFT 수행 및 클리핑
        output_signal = compute_ifft(output_spectrum)
        output_signal = np.clip(output_signal, -1.0, 1.0)
        
        # 6. 에너지 dB 계산
        # 잔여 신호 계산: input + anti-noise (상쇄 간섭)
        residual_signal = input_signal + output_signal
        
        in_db = calculate_db(input_signal)
        out_db = calculate_db(output_signal)
        res_db = calculate_db(residual_signal)
        
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        
        snapshot = AncSnapshot(
            input_db=in_db,
            output_db=out_db,
            residual_db=res_db,
            processing_time_ms=elapsed_ms,
            peak_frequency_hz=peak_hz,
            output_peak_frequency_hz=out_peak_hz,
            input_spectrum_db=input_spec_db,
            output_spectrum_db=output_spec_db
        )
        return output_signal, snapshot

    def _audio_callback(self, indata, outdata, frames, time_info, status):
        """sounddevice 라이브러리의 실시간 오디오 입력/출력 콜백"""
        input_signal = indata[:, 0]
        output_signal, snapshot = self._process_frame(input_signal)
        outdata[:, 0] = output_signal
        
        # UI 업데이트 스로틀링
        now = time.time()
        if now - self.last_snapshot_time >= self.snapshot_interval:
            self.last_snapshot_time = now
            self._dispatch_snapshot(snapshot)

    def _simulation_loop(self):
        """오디오 하드웨어가 없을 때 실행되는 가상 신호 시뮬레이션 루프"""
        frame_duration = self.fft_size / self.sample_rate  # 예: 1024 / 48000 = ~21.3ms
        t = 0.0
        
        while self.running:
            start_loop = time.perf_counter()
            
            # 가상 마이크 입력 신호 생성
            # 1. 440Hz 기본 타겟 노이즈 신호 (진폭 0.4)
            # 2. 1200Hz 부가 신호 (진폭 0.15)
            # 3. 화이트 노이즈 성분
            sample_times = t + np.arange(self.fft_size) / self.sample_rate
            noise = np.random.normal(0, 0.05, self.fft_size)
            sig_440 = 0.4 * np.sin(2.0 * np.pi * 440.0 * sample_times)
            sig_1200 = 0.15 * np.sin(2.0 * np.pi * 1200.0 * sample_times)
            input_signal = sig_440 + sig_1200 + noise
            
            t += frame_duration
            
            # 신호 처리
            _, snapshot = self._process_frame(input_signal)
            
            # UI 업데이트 스로틀링
            now = time.time()
            if now - self.last_snapshot_time >= self.snapshot_interval:
                self.last_snapshot_time = now
                self._dispatch_snapshot(snapshot)
                
            # 프레임 주기 맞춤 sleep
            elapsed = time.perf_counter() - start_loop
            sleep_time = max(0.001, frame_duration - elapsed)
            time.sleep(sleep_time)

    def _dispatch_snapshot(self, snapshot: AncSnapshot):
        if self.on_snapshot_callback:
            # 잔여 신호 히스토리 업데이트
            self.residual_history.append(snapshot.residual_db)
            if len(self.residual_history) > self.history_size:
                self.residual_history.pop(0)
            
            snapshot.residual_history_db = list(self.residual_history)
            self.on_snapshot_callback(snapshot)
