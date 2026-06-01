import numpy as np

def apply_hann_window(signal: np.ndarray) -> np.ndarray:
    """입력 신호에 Hann window를 적용하여 스펙트럼 누설을 완화합니다.
    공식: 0.5 - 0.5 * cos(2*pi*i / (N-1))
    """
    n = len(signal)
    if n <= 1:
        return signal.copy()
    # numpy의 hanning 함수는 공식과 동일한 윈도우를 생성합니다.
    window = 0.5 - 0.5 * np.cos((2.0 * np.pi * np.arange(n)) / (n - 1))
    return signal * window

def compute_fft(signal: np.ndarray) -> np.ndarray:
    """실시간 입력 프레임에 대해 FFT를 수행합니다."""
    return np.fft.fft(signal)

def compute_ifft(spectrum: np.ndarray) -> np.ndarray:
    """반대파 주파수 스펙트럼을 IFFT를 수행해 시간 영역 신호로 복원합니다."""
    return np.fft.ifft(spectrum).real

def calculate_db(signal: np.ndarray, eps: float = 1e-9) -> float:
    """RMS 기반 신호의 에너지 dB를 계산합니다."""
    if len(signal) == 0:
        return -120.0
    rms = np.sqrt(np.mean(signal ** 2))
    return float(20.0 * np.log10(rms + eps))

def magnitude_db(spectrum: np.ndarray) -> np.ndarray:
    """복소 스펙트럼에 대한 magnitude dB를 계산합니다. (절반 대역만 반환)"""
    half = len(spectrum) // 2
    mag = np.abs(spectrum[:half])
    return 20.0 * np.log10(mag + 1e-12)

def get_peak_frequency(spectrum: np.ndarray, sample_rate: int) -> float:
    """가장 에너지가 높은 peak 주파수를 Hz 단위로 반환합니다."""
    half = len(spectrum) // 2
    if half <= 0:
        return 0.0
    mag = np.abs(spectrum[:half])
    peak_bin = np.argmax(mag)
    return float(peak_bin * sample_rate / len(spectrum))
