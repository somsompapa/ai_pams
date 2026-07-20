"""YamlPolicyRepository 통합 테스트.

실제 config/ 파일을 로드해 저장소 구현과 기본 설정 파일 양쪽을 함께 검증한다.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from pams.ips.domain import Severity
from pams.ips.infrastructure import ConfigParseError, YamlPolicyRepository
from pams.shared_kernel.domain import AssetClass, Currency, Percentage

PROJECT_ROOT = Path(__file__).resolve().parents[3]
IPS_PATH = PROJECT_ROOT / "config" / "ips" / "default.yaml"
RULES_PATH = PROJECT_ROOT / "config" / "rules" / "default.yaml"


class TestLoadDefaultConfig:
    def test_load_succeeds(self) -> None:
        policy = YamlPolicyRepository(ips_path=IPS_PATH, rules_path=RULES_PATH).load()
        assert policy.name
        assert policy.base_currency is Currency.KRW

    def test_targets_cover_required_asset_classes(self) -> None:
        policy = YamlPolicyRepository(ips_path=IPS_PATH, rules_path=RULES_PATH).load()
        classes = {t.asset_class for t in policy.targets}
        assert AssetClass.CASH in classes
        total = sum((t.target.ratio for t in policy.targets), Decimal(0))
        assert Percentage.from_ratio(total) == Percentage.from_percent(100)

    def test_rules_loaded_with_severity(self) -> None:
        policy = YamlPolicyRepository(ips_path=IPS_PATH, rules_path=RULES_PATH).load()
        assert policy.rules, "기본 규칙이 최소 1개는 있어야 한다"
        by_id = {rule.rule_id: rule for rule in policy.rules}
        assert "min-cash-weight" in by_id
        assert by_id["min-cash-weight"].severity is Severity.VIOLATION

    def test_exceptional_position_rule_loaded(self) -> None:
        """portfolio_rules.md P-3 초우량 예외 30% 한도 규칙."""
        policy = YamlPolicyRepository(ips_path=IPS_PATH, rules_path=RULES_PATH).load()
        by_id = {rule.rule_id: rule for rule in policy.rules}
        assert "max-exceptional-position" in by_id
        assert by_id["max-exceptional-position"].severity is Severity.VIOLATION

    def test_sector_concentration_rule_loaded(self) -> None:
        """portfolio_rules.md P-4(v1.6.1) 섹터 집중도 35% 한도 규칙."""
        policy = YamlPolicyRepository(ips_path=IPS_PATH, rules_path=RULES_PATH).load()
        by_id = {rule.rule_id: rule for rule in policy.rules}
        assert "max-sector-weight" in by_id
        assert by_id["max-sector-weight"].severity is Severity.VIOLATION


class TestParseErrors:
    def write(self, path: Path, content: str) -> Path:
        path.write_text(content, encoding="utf-8")
        return path

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigParseError):
            YamlPolicyRepository(ips_path=tmp_path / "nope.yaml", rules_path=RULES_PATH).load()

    def test_invalid_yaml_syntax(self, tmp_path: Path) -> None:
        bad = self.write(tmp_path / "bad.yaml", "name: [unclosed")
        with pytest.raises(ConfigParseError):
            YamlPolicyRepository(ips_path=bad, rules_path=RULES_PATH).load()

    def test_unknown_asset_class(self, tmp_path: Path) -> None:
        bad = self.write(
            tmp_path / "ips.yaml",
            """
name: 잘못된 헌장
base_currency: KRW
allocation_targets:
  - asset_class: real_estate
    target_percent: "100"
    band_percent: "5"
""",
        )
        with pytest.raises(ConfigParseError, match="real_estate"):
            YamlPolicyRepository(ips_path=bad, rules_path=RULES_PATH).load()

    def test_unknown_operator(self, tmp_path: Path) -> None:
        ips = self.write(
            tmp_path / "ips.yaml",
            """
name: 헌장
base_currency: KRW
allocation_targets:
  - asset_class: cash
    target_percent: "100"
    band_percent: "0"
""",
        )
        rules = self.write(
            tmp_path / "rules.yaml",
            """
rules:
  - id: broken
    description: 잘못된 연산자
    severity: violation
    when:
      - metric: vix
        operator: bigger_than
        value: "35"
    then:
      action: noop
""",
        )
        with pytest.raises(ConfigParseError, match="bigger_than"):
            YamlPolicyRepository(ips_path=ips, rules_path=rules).load()

    def test_domain_violation_reported_as_config_error(self, tmp_path: Path) -> None:
        """합계 100%가 아닌 목표비중은 도메인 검증에 걸리고, 설정 오류로 감싸져 보고된다."""
        bad = self.write(
            tmp_path / "ips.yaml",
            """
name: 합계가 틀린 헌장
base_currency: KRW
allocation_targets:
  - asset_class: cash
    target_percent: "50"
    band_percent: "5"
""",
        )
        with pytest.raises(ConfigParseError):
            YamlPolicyRepository(ips_path=bad, rules_path=RULES_PATH).load()
