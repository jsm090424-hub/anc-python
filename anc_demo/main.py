import os
import json
import time
import numpy as np
from typing import Optional, List, Dict, Any

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Button, Label, Input, RadioSet, RadioButton, DataTable
from textual.containers import Vertical, Horizontal, Grid, Container
from textual.widget import Widget
from textual.binding import Binding
from rich.text import Text
from rich.panel import Panel
from rich.table import Table

from .engine import AncEngine, AncSnapshot
from .preferences import AncPreferences, AncPreset

# UI용 텍스트 기반 그래프 위젯
class SpectrumPlot(Widget):
    """FFT 주파수 스펙트럼을 그리는 TUI 위젯"""
    def __init__(self, title: str, is_output: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.title = title
        self.is_output = is_output
        self.spectrum_data = np.zeros(512)
        self.low_freq = 50.0
        self.high_freq = 1200.0
        self.sample_rate = 48000
        self.peak_hz = 0.0

    def update_spectrum(self, data: np.ndarray, low_freq: float, high_freq: float, peak_hz: float):
        self.spectrum_data = data
        self.low_freq = low_freq
        self.high_freq = high_freq
        self.peak_hz = peak_hz
        self.refresh()

    def render(self) -> Panel:
        width = max(20, self.size.width - 6)
        height = max(4, self.size.height - 3)
        
        # 512개의 bin 데이터를 터미널 폭(width)에 맞춰 버킷팅
        num_buckets = width
        bucket_size = len(self.spectrum_data) // num_buckets
        if bucket_size <= 0:
            bucket_size = 1
            num_buckets = len(self.spectrum_data)

        buckets = []
        for i in range(num_buckets):
            start_idx = i * bucket_size
            end_idx = min(len(self.spectrum_data), (i + 1) * bucket_size)
            val = np.mean(self.spectrum_data[start_idx:end_idx]) if start_idx < end_idx else -120.0
            buckets.append(val)

        # 블록 문자 정의
        blocks = [" ", " ", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
        
        # 캔버스 2D 배열 생성 (공백 문자 채움)
        canvas = [[" " for _ in range(num_buckets)] for _ in range(height)]
        
        # 주파수 필터 영역 하이라이트 마킹을 위한 플래그 계산
        fft_size = len(self.spectrum_data) * 2
        low_bin = int((self.low_freq / self.sample_rate) * fft_size)
        high_bin = int((self.high_freq / self.sample_rate) * fft_size)
        
        # peak 주파수 버킷 찾기
        peak_bin_idx = int((self.peak_hz / self.sample_rate) * fft_size)
        peak_bucket = -1
        if 0 <= peak_bin_idx < len(self.spectrum_data) and bucket_size > 0:
            peak_bucket = peak_bin_idx // bucket_size

        for col in range(num_buckets):
            val = buckets[col]
            # dB 값 (-100dB ~ 0dB)을 높이로 매핑
            normalized = (val + 100.0) / 100.0
            normalized = max(0.0, min(1.0, normalized))
            
            fill_height_float = normalized * height
            fill_height = int(fill_height_float)
            fraction = fill_height_float - fill_height
            block_idx = int(fraction * 8)
            
            for row in range(height):
                r_idx = height - 1 - row
                if row < fill_height:
                    canvas[r_idx][col] = blocks[8]
                elif row == fill_height and block_idx > 0:
                    canvas[r_idx][col] = blocks[block_idx]

        # Rich 텍스트 조립
        text_lines = []
        for row in range(height):
            line_text = Text()
            for col in range(num_buckets):
                char = canvas[row][col]
                
                # 해당 버킷의 주파수 대역 판단
                bin_start = col * bucket_size
                is_in_range = (low_bin <= bin_start <= high_bin)
                
                # Peak 마커 표시 (최상단 줄에 표시 가능 시 표시)
                if row == 0 and col == peak_bucket and char == " ":
                    line_text.append("▼", style="bold red")
                elif is_in_range:
                    if self.is_output:
                        line_text.append(char, style="cyan")
                    else:
                        line_text.append(char, style="green")
                else:
                    line_text.append(char, style="bright_black")
            text_lines.append(line_text)
            
        # 하단 축 라벨 정보 조립
        axis_info = f"20Hz [dim]◀━ 필터대역: {int(self.low_freq)}Hz~{int(self.high_freq)}Hz ━▶[/dim] {self.sample_rate//2}Hz (Peak: {self.peak_hz:.1f}Hz)"
        panel_title = f"[bold]{self.title}[/bold] {axis_info}"
        
        full_text = Text("\n").join(text_lines)
        return Panel(full_text, title=panel_title, border_style="cyan" if self.is_output else "green")

class HistoryPlot(Widget):
    """잔여 신호(dB) 히스토리 꺾은선 차트를 그리는 TUI 위젯"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.history = []

    def update_history(self, history: List[float]):
        self.history = history
        self.refresh()

    def render(self) -> Panel:
        width = max(20, self.size.width - 6)
        height = max(4, self.size.height - 3)
        
        # 가로 폭에 맞게 히스토리 버킷팅
        if not self.history:
            return Panel(Text("신호 대기 중...", style="dim italic"), title="잔여 신호 히스토리 (dB)")
            
        num_points = min(width, len(self.history))
        data_subset = self.history[-num_points:]
        
        # 캔버스 2D 배열 생성
        canvas = [[" " for _ in range(num_points)] for _ in range(height)]
        
        # 가이드라인 위치 계산 (-20dB, -40dB, -60dB)
        # dB 가용 범위: -100dB ~ 0dB
        def db_to_row(db_val: float) -> int:
            norm = (db_val + 100.0) / 100.0
            norm = max(0.0, min(1.0, norm))
            row = int(norm * (height - 1))
            return height - 1 - row

        g_rows = {
            -20: db_to_row(-20.0),
            -40: db_to_row(-40.0),
            -60: db_to_row(-60.0)
        }
        
        # 가이드라인 배경 선 그리기
        for db, r in g_rows.items():
            if 0 <= r < height:
                for col in range(num_points):
                    canvas[r][col] = "┄"

        # 데이터 포인트 꺾은선 렌더링
        for col in range(num_points):
            db = data_subset[col]
            r = db_to_row(db)
            if 0 <= r < height:
                canvas[r][col] = "●"
                
        # Rich 텍스트 조합
        text_lines = []
        for row in range(height):
            line_text = Text()
            
            # 행별 가이드라인 레이블 추가
            db_label = ""
            for db, r_idx in g_rows.items():
                if row == r_idx:
                    db_label = f"{db}dB"
                    break
            if not db_label:
                db_label = "     "
            else:
                db_label = f"{db_label:>5}"
                
            line_text.append(f"[dim]{db_label}[/dim] │ ")
            
            for col in range(num_points):
                char = canvas[row][col]
                if char == "●":
                    # 잔여 dB 수준에 따른 동적 색상
                    val = data_subset[col]
                    if val <= -60.0:
                        line_text.append(char, style="bold green")
                    elif val <= -40.0:
                        line_text.append(char, style="yellow")
                    else:
                        line_text.append(char, style="bold red")
                else:
                    line_text.append(char, style="dim magenta")
            text_lines.append(line_text)
            
        full_text = Text("\n").join(text_lines)
        return Panel(full_text, title="[bold]잔여 신호 실시간 히스토리[/bold] [dim](상쇄 타겟: -60dB 이하)[/dim]", border_style="magenta")


# TUI 메인 앱
class AncTuiApp(App):
    TITLE = "실시간 ANC(능동 소음 제어) 푸리에 상쇄 모듈"
    SUB_TITLE = "TUI Dashboard v1.0.0"
    
    CSS = """
    #app_grid {
        grid-size: 2;
        grid-columns: 1fr 1fr;
        padding: 1;
        height: 1fr;
    }
    
    #left_panel {
        border: round white;
        padding: 1;
        background: $panel;
        height: 100%;
        overflow-y: scroll;
    }
    
    #right_panel {
        border: round white;
        padding: 1;
        background: $panel;
        height: 100%;
        overflow-y: scroll;
    }
    
    .panel_title {
        text-align: center;
        background: $accent;
        color: white;
        text-style: bold;
        padding: 0 1;
        margin-bottom: 1;
    }

    .section_title {
        text-style: bold;
        color: cyan;
        margin-top: 1;
        margin-bottom: 0;
    }

    .stat_row {
        height: 1;
        margin-bottom: 0;
    }

    .param_control {
        height: 3;
        margin-bottom: 1;
        align: left middle;
    }

    .param_input {
        width: 30%;
        margin-right: 1;
    }

    .inc_dec_btn {
        min-width: 5;
        margin-right: 1;
    }
    
    #plot_input {
        height: 10;
    }
    
    #plot_output {
        height: 10;
    }
    
    #plot_history {
        height: 8;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "종료", show=True),
        Binding("space", "toggle_engine", "엔진 시작/중지", show=True),
    ]

    def __init__(self):
        super().__init__()
        self.prefs = AncPreferences()
        self.engine = AncEngine(ui_fps=15)
        self.loaded_settings = self.prefs.load()
        self.slot_names = self.prefs.load_slot_names()
        
        # 엔진 파라미터 적용
        self.engine.update_params(
            anti_noise_gain=self.loaded_settings["antiGain"],
            low_freq_hz=self.loaded_settings["lowFreqHz"],
            high_freq_hz=self.loaded_settings["highFreqHz"]
        )

    def compose(self) -> ComposeResult:
        yield Header()
        
        with Grid(id="app_grid"):
            # 왼쪽 패널 (제어, 프리셋, 슬롯, 설정 저장 등)
            with Vertical(id="left_panel"):
                yield Label("ANC 제어 및 프리셋 설정", classes="panel_title")
                
                # 엔진 가동 제어
                with Horizontal(classes="stat_row"):
                    yield Button("엔진 시작 (Space)", variant="success", id="btn_toggle")
                    yield Label("  상태: [bold red]중지됨[/bold red]", id="lbl_engine_status")

                # 제어 슬라이더 대체 정밀 인풋 + 버튼
                yield Label("실시간 파라미터 세부 튜닝", classes="section_title")
                
                yield Label("반대파 게인 (Anti-Noise Gain): 0.00 ~ 1.00", id="lbl_slider_gain")
                with Horizontal(classes="param_control"):
                    yield Input(value=f"{self.loaded_settings['antiGain']:.2f}", classes="param_input", id="input_gain")
                    yield Button("-", classes="inc_dec_btn", id="btn_gain_dec")
                    yield Button("+", classes="inc_dec_btn", id="btn_gain_inc")
                
                yield Label("저역 필터 경계 (Low Cutoff): 20Hz ~ 5000Hz", id="lbl_slider_low")
                with Horizontal(classes="param_control"):
                    yield Input(value=f"{int(self.loaded_settings['lowFreqHz'])}", classes="param_input", id="input_low")
                    yield Button("-", classes="inc_dec_btn", id="btn_low_dec")
                    yield Button("+", classes="inc_dec_btn", id="btn_low_inc")
                
                yield Label("고역 필터 경계 (High Cutoff): 20Hz ~ 5000Hz", id="lbl_slider_high")
                with Horizontal(classes="param_control"):
                    yield Input(value=f"{int(self.loaded_settings['highFreqHz'])}", classes="param_input", id="input_high")
                    yield Button("-", classes="inc_dec_btn", id="btn_high_dec")
                    yield Button("+", classes="inc_dec_btn", id="btn_high_inc")

                # 프리셋 선택
                yield Label("ANC 대역 프리셋 선택", classes="section_title")
                preset_options = [
                    ("저주파 대역 상쇄 (Low Rumble)", AncPreset.LOW_RUMBLE),
                    ("인간 음성대역 상쇄 (Voice Band)", AncPreset.VOICE_BAND),
                    ("광대역 백색소음 상쇄 (Wide Band)", AncPreset.WIDE_BAND)
                ]
                
                active_preset = self.loaded_settings.get("preset", AncPreset.CUSTOM)
                with RadioSet(id="radio_preset"):
                    for label, name in preset_options:
                        yield RadioButton(label, value=(name == active_preset), id=f"preset_{name.lower()}")

            # 오른쪽 패널 (지표, 그래프)
            with Vertical(id="right_panel"):
                yield Label("실시간 신호 및 스펙트럼 시각화", classes="panel_title")
                
                # 수치 지표 (RMS dB, 저감량 등)
                with Vertical(id="stat_card"):
                    yield Label("입력 소음 레벨: [bold green]-120.0 dB[/bold green]", id="lbl_stat_input")
                    yield Label("생성 반대파 레벨: [bold cyan]-120.0 dB[/bold cyan]", id="lbl_stat_output")
                    yield Label("추정 잔여 레벨: [bold magenta]-120.0 dB[/bold magenta]", id="lbl_stat_residual")
                    yield Label("추정 감쇄량 (Reduction): [bold yellow]0.0 dB[/bold yellow]", id="lbl_stat_reduction")
                    yield Label("주요 피크 주파수: [bold]0.0 Hz[/bold] (반대파: 0.0 Hz)", id="lbl_stat_peaks")
                    yield Label("프레임 처리 지연: [dim]0.00 ms[/dim]", id="lbl_stat_time")
                
                # 실시간 스펙트럼 및 히스토리 차트
                yield SpectrumPlot("입력 스펙트럼 (Input Spectrum)", is_output=False, id="plot_input")
                yield SpectrumPlot("생성 반대파 (Anti-Phase Spectrum)", is_output=True, id="plot_output")
                yield HistoryPlot(id="plot_history")
                    
        yield Footer()

    def on_mount(self) -> None:
        # 원리 설명 안내 패널을 푸터에 바인딩
        self.log("ANC TUI App Mounted")

    def action_toggle_engine(self) -> None:
        self.toggle_engine()

    def toggle_engine(self):
        lbl = self.query_one("#lbl_engine_status", Label)
        btn = self.query_one("#btn_toggle", Button)
        
        if self.engine.is_running():
            self.engine.stop()
            lbl.update("  상태: [bold red]중지됨[/bold red]")
            btn.label = "엔진 시작 (Space)"
            btn.variant = "success"
        else:
            success, msg = self.engine.start(self.on_snapshot_received)
            if success:
                lbl.update("  상태: [bold green]실행 중 (실제 장치)[/bold green]")
            else:
                lbl.update(f"  상태: [bold yellow]실행 중 (시뮬레이션 fallback)[/bold yellow]")
            btn.label = "엔진 중지 (Space)"
            btn.variant = "error"
            
            # 하드웨어 에러 메시지가 있을 경우 알림 표시
            if "장치를 찾을 수 없어" in msg:
                self.notify(msg, title="오디오 디바이스 시뮬레이터 구동", severity="warning")

    def on_snapshot_received(self, snapshot: AncSnapshot):
        # 스레드 안전하게 메인 UI 스레드에서 위젯 상태 업데이트
        self.call_from_thread(self.update_ui_with_snapshot, snapshot)

    def update_ui_with_snapshot(self, s: AncSnapshot):
        # 1. 수치 레이블 업데이트
        self.query_one("#lbl_stat_input", Label).update(f"입력 소음 레벨: [bold green]{s.input_db:.1f} dB[/bold green]")
        self.query_one("#lbl_stat_output", Label).update(f"생성 반대파 레벨: [bold cyan]{s.output_db:.1f} dB[/bold cyan]")
        self.query_one("#lbl_stat_residual", Label).update(f"추정 잔여 레벨: [bold magenta]{s.residual_db:.1f} dB[/bold magenta]")
        
        reduction = s.input_db - s.residual_db
        self.query_one("#lbl_stat_reduction", Label).update(f"추정 감쇄량 (Reduction): [bold yellow]{reduction:.1f} dB[/bold yellow]")
        self.query_one("#lbl_stat_peaks", Label).update(f"주요 피크 주파수: [bold]{s.peak_frequency_hz:.1f} Hz[/bold] (반대파: {s.output_peak_frequency_hz:.1f} Hz)")
        self.query_one("#lbl_stat_time", Label).update(f"프레임 처리 지연: [dim]{s.processing_time_ms:.2f} ms[/dim]")

        # 2. 실시간 그래프 업데이트
        self.query_one("#plot_input", SpectrumPlot).update_spectrum(
            s.input_spectrum_db, self.loaded_settings["lowFreqHz"], self.loaded_settings["highFreqHz"], s.peak_frequency_hz
        )
        self.query_one("#plot_output", SpectrumPlot).update_spectrum(
            s.output_spectrum_db, self.loaded_settings["lowFreqHz"], self.loaded_settings["highFreqHz"], s.output_peak_frequency_hz
        )
        self.query_one("#plot_history", HistoryPlot).update_history(s.residual_history_db)

    # UI 위젯 인터랙션 처리 (Input 변경 핸들러)
    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "input_gain":
            try:
                val = float(event.value)
                val = max(0.0, min(1.0, val))
                self.loaded_settings["antiGain"] = val
                self._sync_params_with_engine()
            except ValueError:
                pass
        elif event.input.id == "input_low":
            try:
                val = float(event.value)
                val = max(20.0, min(5000.0, val))
                self.loaded_settings["lowFreqHz"] = val
                self._sync_params_with_engine()
            except ValueError:
                pass
        elif event.input.id == "input_high":
            try:
                val = float(event.value)
                val = max(20.0, min(5000.0, val))
                self.loaded_settings["highFreqHz"] = val
                self._sync_params_with_engine()
            except ValueError:
                pass

    def _sync_params_with_engine(self):
        # 파라미터를 조작하면 프리셋 선택 상태를 초기화(CUSTOM으로 변경하되 TUI 라디오 선택은 해제)
        self.loaded_settings["preset"] = AncPreset.CUSTOM
        self.query_one("#radio_preset", RadioSet)._selected_id = None
        self.prefs.save(self.loaded_settings)
        self.engine.update_params(
            self.loaded_settings["antiGain"],
            self.loaded_settings["lowFreqHz"],
            self.loaded_settings["highFreqHz"]
        )

    def _update_gain(self, val: float):
        self.loaded_settings["antiGain"] = val
        self.query_one("#input_gain", Input).value = f"{val:.2f}"
        self._sync_params_with_engine()

    def _update_low(self, val: float):
        self.loaded_settings["lowFreqHz"] = val
        self.query_one("#input_low", Input).value = f"{int(val)}"
        self._sync_params_with_engine()

    def _update_high(self, val: float):
        self.loaded_settings["highFreqHz"] = val
        self.query_one("#input_high", Input).value = f"{int(val)}"
        self._sync_params_with_engine()

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        p_id = event.pressed.id
        if not p_id:
            return
            
        preset_map = {
            "preset_low_rumble": AncPreset.LOW_RUMBLE,
            "preset_voice_band": AncPreset.VOICE_BAND,
            "preset_wide_band": AncPreset.WIDE_BAND
        }
        
        target_preset = preset_map.get(p_id)
        if not target_preset:
            return

        # 프리셋 파라미터 적용
        gain, low, high = AncPreset.get_preset_values(target_preset)
        self.loaded_settings["preset"] = target_preset
        self.loaded_settings["antiGain"] = gain
        self.loaded_settings["lowFreqHz"] = low
        self.loaded_settings["highFreqHz"] = high

        # 인풋 필드 강제 업데이트
        self.query_one("#input_gain", Input).value = f"{gain:.2f}"
        self.query_one("#input_low", Input).value = f"{int(low)}"
        self.query_one("#input_high", Input).value = f"{int(high)}"

        self.prefs.save(self.loaded_settings)
        self.engine.update_params(gain, low, high)
        self.notify(f"프리셋 '{AncPreset.get_label(target_preset)}'이 적용되었습니다.", title="프리셋 로드")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if not btn_id:
            return

        if btn_id == "btn_toggle":
            self.toggle_engine()


def main():
    app = AncTuiApp()
    app.run()

if __name__ == "__main__":
    main()
