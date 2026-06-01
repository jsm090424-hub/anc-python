import os
import re
import json
import hashlib
import time
from typing import Optional, Dict, Any, List

class AncPreset:
    LOW_RUMBLE = "LOW_RUMBLE"
    VOICE_BAND = "VOICE_BAND"
    WIDE_BAND = "WIDE_BAND"
    CUSTOM = "CUSTOM"

    @classmethod
    def get_preset_values(cls, preset: str) -> tuple[float, float, float]:
        """프리셋 이름에 따른 (gain, lowFreq, highFreq) 값을 반환합니다."""
        p = preset.upper()
        if p == cls.LOW_RUMBLE:
            return 0.85, 20.0, 280.0
        elif p == cls.VOICE_BAND:
            return 0.65, 250.0, 2500.0
        elif p == cls.WIDE_BAND:
            return 0.55, 50.0, 5000.0
        else: # CUSTOM
            return 0.6, 50.0, 1200.0

    @classmethod
    def get_label(cls, preset: str) -> str:
        p = preset.upper()
        if p == cls.LOW_RUMBLE:
            return "저주파"
        elif p == cls.VOICE_BAND:
            return "음성대역"
        elif p == cls.WIDE_BAND:
            return "광대역"
        return "사용자"

class AncPreferences:
    def __init__(self, filepath: str = "anc_settings.json"):
        self.filepath = os.path.abspath(filepath)
        self.history_limit = 5
        self._ensure_file()

    def _default_data(self) -> Dict[str, Any]:
        return {
            "current": {
                "preset": AncPreset.CUSTOM,
                "antiGain": 0.6,
                "lowFreqHz": 50.0,
                "highFreqHz": 1200.0
            },
            "slot1": {
                "preset": AncPreset.CUSTOM,
                "antiGain": 0.6,
                "lowFreqHz": 50.0,
                "highFreqHz": 1200.0
            },
            "slot2": {
                "preset": AncPreset.CUSTOM,
                "antiGain": 0.6,
                "lowFreqHz": 50.0,
                "highFreqHz": 1200.0
            },
            "slotNames": {
                "slot1": "슬롯1",
                "slot2": "슬롯2"
            },
            "rollbackHistory": []
        }

    def _ensure_file(self):
        if not os.path.exists(self.filepath):
            self._write_raw(self._default_data())

    def _read_raw(self) -> Dict[str, Any]:
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 데이터 보정
                default = self._default_data()
                for key in ["current", "slot1", "slot2", "slotNames", "rollbackHistory"]:
                    if key not in data:
                        data[key] = default[key]
                return data
        except Exception:
            return self._default_data()

    def _write_raw(self, data: Dict[str, Any]):
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"설정 저장 실패: {e}")

    def load(self) -> Dict[str, Any]:
        data = self._read_raw()
        return data["current"]

    def save(self, current_settings: Dict[str, Any]):
        data = self._read_raw()
        data["current"] = self._clamp_settings(current_settings)
        self._write_raw(data)

    def load_user_slot(self, slot: int) -> Dict[str, Any]:
        data = self._read_raw()
        key = f"slot{slot}"
        if key in data:
            return data[key]
        return self._default_data()["slot1"]

    def save_user_slot(self, slot: int, settings: Dict[str, Any]):
        data = self._read_raw()
        key = f"slot{slot}"
        data[key] = self._clamp_settings(settings)
        self._write_raw(data)

    def load_slot_names(self) -> Dict[str, str]:
        data = self._read_raw()
        return data.get("slotNames", {"slot1": "슬롯1", "slot2": "슬롯2"})

    def save_slot_name(self, slot: int, name: str):
        data = self._read_raw()
        safe_name = re.sub(r"\s+", " ", name.strip())[:12]
        if not safe_name:
            safe_name = f"슬롯{slot}"
        if "slotNames" not in data:
            data["slotNames"] = {}
        data["slotNames"][f"slot{slot}"] = safe_name
        self._write_raw(data)

    def load_rollback_history(self) -> List[Dict[str, Any]]:
        data = self._read_raw()
        return data.get("rollbackHistory", [])

    def _clamp_settings(self, s: Dict[str, Any]) -> Dict[str, Any]:
        preset = s.get("preset", AncPreset.CUSTOM)
        gain = float(s.get("antiGain", 0.6))
        low = float(s.get("lowFreqHz", 50.0))
        high = float(s.get("highFreqHz", 1200.0))

        # Clamping
        gain = max(0.0, min(1.0, gain))
        low = max(20.0, min(5000.0, low))
        high = max(20.0, min(5000.0, high))
        if high < low:
            high = low

        return {
            "preset": preset,
            "antiGain": gain,
            "lowFreqHz": low,
            "highFreqHz": high
        }

    def _compute_checksum(self, payload: Dict[str, Any]) -> str:
        # JSON 직렬화 시 공백을 제거하고 키 정렬을 보장하여 일관된 체크섬 획득
        raw = json.dumps(payload, separators=(',', ':'), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

    def export_all_as_json(self, app_version: str = "py-1.0.0") -> str:
        data = self._read_raw()
        payload = {
            "schemaVersion": 1,
            "exportedAtEpochMs": int(time.time() * 1000),
            "appVersion": app_version,
            "current": data["current"],
            "slot1": data["slot1"],
            "slot2": data["slot2"],
            "slotNames": data["slotNames"]
        }
        checksum = self._compute_checksum(payload)
        payload["checksum"] = checksum
        return json.dumps(payload, indent=2, ensure_ascii=False)

    def parse_import_bundle(self, raw_json: str) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        """JSON 문자열을 파싱하고 유효성 검사 및 checksum 검증을 수행합니다.
        성공 시 (bundle_data, None) 반환, 실패 시 (None, error_message) 반환.
        """
        if not raw_json.strip():
            return None, "가져올 JSON이 비어 있습니다."
        try:
            root = json.loads(raw_json)
        except json.JSONDecodeError:
            return None, "JSON 형식이 올바르지 않습니다."

        schema_version = root.get("schemaVersion", 1)
        if schema_version != 1:
            return None, f"지원하지 않는 schemaVersion: {schema_version}"

        expected_checksum = root.get("checksum", "")
        if expected_checksum:
            # checksum 검증을 위해 checksum 키 제거 후 계산
            payload_for_check = dict(root)
            payload_for_check.pop("checksum", None)
            actual_checksum = self._compute_checksum(payload_for_check)
            if expected_checksum.lower() != actual_checksum.lower():
                # 호환성을 위해 fallback: 정밀 비교 불일치 경고이나 파이썬 간 검증 보장
                # 여기서는 strict하게 검증
                return None, "체크섬이 일치하지 않습니다. JSON 무결성을 확인하세요."

        for req_field in ["current", "slot1", "slot2"]:
            if req_field not in root:
                return None, f"{req_field} 설정이 존재하지 않습니다."

        # 슬롯명 처리
        slot_names = root.get("slotNames", {"slot1": "슬롯1", "slot2": "슬롯2"})
        if not isinstance(slot_names, dict):
            slot_names = {"slot1": "슬롯1", "slot2": "슬롯2"}

        bundle = {
            "current": self._clamp_settings(root["current"]),
            "slot1": self._clamp_settings(root["slot1"]),
            "slot2": self._clamp_settings(root["slot2"]),
            "slotNames": {
                "slot1": slot_names.get("slot1", "슬롯1"),
                "slot2": slot_names.get("slot2", "슬롯2")
            }
        }
        return bundle, None

    def apply_imported_bundle(self, bundle: Dict[str, Any]):
        data = self._read_raw()
        
        # 1. 롤백 백업 생성
        rollback_entry = {
            "id": f"{int(time.time() * 1000)}-{os.urandom(2).hex()}",
            "createdAt": int(time.time() * 1000),
            "reason": "가져오기 적용",
            "settings": dict(data["current"]),
            "slots": {
                "slot1": dict(data["slot1"]),
                "slot2": dict(data["slot2"]),
                "slotNames": dict(data["slotNames"])
            }
        }
        history = [rollback_entry] + data.get("rollbackHistory", [])
        data["rollbackHistory"] = history[:self.history_limit]

        # 2. 데이터 적용
        data["current"] = bundle["current"]
        data["slot1"] = bundle["slot1"]
        data["slot2"] = bundle["slot2"]
        data["slotNames"] = bundle["slotNames"]
        
        self._write_raw(data)

    def build_diff_summary(self, bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
        """가져온 번들과 현재 설정의 차이점을 추출하고, 위험 여부를 판별합니다."""
        current_data = self._read_raw()
        items = []

        def append_diff(label: str, before: Dict[str, Any], after: Dict[str, Any]):
            # 프리셋 비교
            if before["preset"] != after["preset"]:
                items.append({
                    "label": f"{label} 프리셋",
                    "before": AncPreset.get_label(before["preset"]),
                    "after": AncPreset.get_label(after["preset"]),
                    "risky": False
                })
            # 게인 비교
            if before["antiGain"] != after["antiGain"]:
                diff = abs(before["antiGain"] - after["antiGain"])
                items.append({
                    "label": f"{label} 게인",
                    "before": f"{before['antiGain']:.2f}",
                    "after": f"{after['antiGain']:.2f}",
                    "risky": diff >= 0.2 or after["antiGain"] >= 0.9
                })
            # 저역 비교
            if before["lowFreqHz"] != after["lowFreqHz"]:
                items.append({
                    "label": f"{label} 저역",
                    "before": f"{int(before['lowFreqHz'])}Hz",
                    "after": f"{int(after['lowFreqHz'])}Hz",
                    "risky": after["lowFreqHz"] <= 30.0
                })
            # 고역 비교
            if before["highFreqHz"] != after["highFreqHz"]:
                items.append({
                    "label": f"{label} 고역",
                    "before": f"{int(before['highFreqHz'])}Hz",
                    "after": f"{int(after['highFreqHz'])}Hz",
                    "risky": after["highFreqHz"] >= 4500.0
                })

        append_diff("현재 설정", current_data["current"], bundle["current"])
        append_diff("슬롯1", current_data["slot1"], bundle["slot1"])
        append_diff("슬롯2", current_data["slot2"], bundle["slot2"])

        # 슬롯 이름 비교
        b_names = current_data["slotNames"]
        a_names = bundle["slotNames"]
        if b_names.get("slot1", "슬롯1") != a_names.get("slot1", "슬롯1"):
            items.append({
                "label": "슬롯1 이름",
                "before": b_names.get("slot1", "슬롯1"),
                "after": a_names.get("slot1", "슬롯1"),
                "risky": False
            })
        if b_names.get("slot2", "슬롯2") != a_names.get("slot2", "슬롯2"):
            items.append({
                "label": "슬롯2 이름",
                "before": b_names.get("slot2", "슬롯2"),
                "after": a_names.get("slot2", "슬롯2"),
                "risky": False
            })
        
        return items

    def rollback_from_history(self, entry_id: str) -> Optional[str]:
        data = self._read_raw()
        history = data.get("rollbackHistory", [])
        target = None
        for item in history:
            if item.get("id") == entry_id:
                target = item
                break
        
        if not target:
            return "해당 되돌리기 이력이 존재하지 않습니다."
        
        # 적용
        data["current"] = target["settings"]
        slots = target["slots"]
        data["slot1"] = slots["slot1"]
        data["slot2"] = slots["slot2"]
        data["slotNames"] = slots["slotNames"]

        # 히스토리에서 해당 항목 제거
        data["rollbackHistory"] = [x for x in history if x.get("id") != entry_id]
        self._write_raw(data)
        return None
