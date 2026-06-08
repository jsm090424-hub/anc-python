# ANC Demo (Python TUI, 3.13)

마이크 입력 신호를 실시간 FFT로 분석해, 선택한 주파수 대역에 대해 반대 위상(anti-phase) 신호를 생성/출력하는 실험용 Python TUI 대시보드입니다. Android 및 Web의 핵심 기능과 무결성 검증, 롤백 스택을 동일하게 구현하였습니다.

## 주요 기능

1. **실시간 신호 처리**: 
   - 실시간 오디오 입력 획득 후 Hann Window 적용 및 FFT 연산 수행.
   - 설정된 주파수 대역(`lowFreqHz` ~ `highFreqHz`)에 대해 반대 위상 복소 신호를 합성하고 mirror 구성 후 IFFT로 시간 신호 복원.
   - RMS 기반 입/출력/잔여 신호 에너지(dB) 및 감쇄량 실시간 계산.
2. **미려한 Textual TUI**:
   - 반응형 레이아웃 및 다채로운 터미널 스타일링 적용.
   - 유니코드 블록 문자를 이용해 실시간 FFT 주파수 스펙트럼 및 대역 하이라이트, Peak 주파수 마커 표시.
   - 점선 가이드라인(-20dB, -40dB, -60dB)이 내장된 잔여 신호 실시간 꺾은선 차트 시각화.
3. **가상 오디오 시뮬레이션 (Fallback)**:
   - 물리적 마이크/스피커 장치가 없거나 가상 컨테이너 환경인 경우, 440Hz 신호와 화이트 노이즈 기반의 가상 입력 프레임을 생성하는 **시뮬레이션 모드**로 자동 Fallback 되어 TUI 인터페이스를 정상 테스트할 수 있습니다.
4. **사용자 슬롯 및 프리셋**:
   - 저주파, 음성대역, 광대역 대역 프리셋 원클릭 설정.
   - 2개의 슬롯에 현재 설정을 슬롯명 변경(12자 제한 및 공백 제거)과 함께 로컬 파일로 저장 및 복원.
5. **안전장치가 설계된 JSON 설정 이관**:
   - `schemaVersion` 및 SHA-256 `checksum` 기반의 무결성 검증.
   - 즉시 반영을 피하고 적용 전 Before/After 테이블 미리보기(Diff) 및 위험(Risky) 설정 강조 모달 팝업 제공.
   - 설정 덮어쓰기 전 기존 설정을 롤백 스택(최대 5개)에 자동 보관하여 안심 복원 가능.

## 컴파일 및 실행 방법

### 사전 준비

- Python 3.13 이상 설치
- `uv` 패키지 관리 도구 설치

- UV를 WINDOWS에서 설치하기
```bash
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 1. 프로젝트 Clone 
c drive root로 이동
```bash
cd c:\
```

작업 디렉토리 생성
```bash
mkdir anc
```

소스 받기 
```bash
git clone https://github.com/jsm090424-hub/anc-python.git
```

소스로 이동 
```bash
cd anc-python
```

### 2. 프로젝트 의존성 설치 및 가상환경 구성
`uv`가 자동으로 Python 3.13 호환 가상환경을 생성하고 의존성을 셋업합니다.
```bash
uv sync
```

### 3. TUI 앱 실행
아래 명령어를 사용하여 즉시 텍스트 기반 대시보드를 구동할 수 있습니다.
```bash
uv run anc-demo
```
또는
```bash
uv run main.py
```

## TUI 단축키
- `Space`: 오디오 엔진 시작 / 중지
- `q`: 프로그램 종료
