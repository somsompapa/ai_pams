"""config/equity_scoring/*.yaml → ScoringConfig 로더."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from pams.equity.domain.scoring_config import EntryBarrierConfig, RiskConfig, ScoringConfig
from pams.shared_kernel.domain import (
    Band,
    BandDirection,
    BandTable,
    CategoricalOption,
    CategoricalTable,
    DomainError,
)


class ScoringConfigError(Exception):
    """스코어링 설정 파일을 ScoringConfig로 변환하는 데 실패했다."""


class YamlScoringConfigLoader:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> ScoringConfig:
        document = self._read()
        try:
            growth = self._require(document, "growth")
            competitiveness = self._require(document, "competitiveness")
            financials = self._require(document, "financials")
            risk = self._require(document, "risk")

            return ScoringConfig(
                revenue_cagr_3y=self._band_table(
                    "growth.revenue_cagr_3y", growth["revenue_cagr_3y"]
                ),
                eps_cagr_3y=self._band_table("growth.eps_cagr_3y", growth["eps_cagr_3y"]),
                industry_tam_cagr=self._band_table(
                    "growth.industry_tam_cagr", growth["industry_tam_cagr"]
                ),
                financial_sector_total_assets_cagr_3y=self._band_table(
                    "growth.financial_sector_total_assets_cagr_3y",
                    growth["financial_sector_total_assets_cagr_3y"],
                ),
                market_share_trend=self._categorical_table(
                    "competitiveness.market_share_trend", competitiveness["market_share_trend"]
                ),
                gross_margin_vs_industry=self._band_table(
                    "competitiveness.gross_margin_vs_industry",
                    competitiveness["gross_margin_vs_industry"],
                ),
                financial_sector_roa_vs_industry=self._band_table(
                    "competitiveness.financial_sector_roa_vs_industry",
                    competitiveness["financial_sector_roa_vs_industry"],
                ),
                entry_barrier=self._entry_barrier(competitiveness["entry_barrier"]),
                roe=self._band_table("financials.roe", financials["roe"]),
                roic_minus_wacc_spread=self._band_table(
                    "financials.roic_minus_wacc_spread", financials["roic_minus_wacc_spread"]
                ),
                op_margin_industry_rank=self._categorical_table(
                    "financials.op_margin_industry_rank", financials["op_margin_industry_rank"]
                ),
                fcf_positive_years=self._categorical_table(
                    "financials.fcf_positive_years", financials["fcf_positive_years"]
                ),
                debt_ratio=self._band_table("financials.debt_ratio", financials["debt_ratio"]),
                risk=self._risk_config(risk),
            )
        except (DomainError, KeyError, ValueError) as error:
            raise ScoringConfigError(f"{self._path}: 잘못된 스코어링 설정: {error}") from error

    def _read(self) -> dict[str, Any]:
        try:
            document = yaml.safe_load(self._path.read_text(encoding="utf-8"))
        except OSError as error:
            raise ScoringConfigError(f"설정 파일을 읽을 수 없다: {self._path}") from error
        except yaml.YAMLError as error:
            raise ScoringConfigError(f"YAML 문법 오류: {self._path}: {error}") from error
        if not isinstance(document, dict):
            raise ScoringConfigError(f"{self._path}: 최상위는 매핑이어야 한다")
        return document

    def _require(self, document: dict[str, Any], key: str) -> Any:
        if key not in document:
            raise ScoringConfigError(f"{self._path}: 필수 항목 '{key}'가 없다")
        return document[key]

    def _decimal(self, label: str, value: object) -> Decimal:
        try:
            return Decimal(str(value))
        except InvalidOperation as error:
            raise ScoringConfigError(
                f"{self._path}.{label}: 숫자로 해석할 수 없다: {value!r}"
            ) from error

    def _band_table(self, label: str, node: dict[str, Any]) -> BandTable:
        direction = BandDirection(node["direction"])
        bands = tuple(
            Band(
                bound=self._decimal(f"{label}.bands[{i}].bound", b["bound"]),
                score=self._decimal(f"{label}.bands[{i}].score", b["score"]),
                label=str(b["label"]),
            )
            for i, b in enumerate(node["bands"])
        )
        return BandTable(
            metric=label,
            max_score=self._decimal(f"{label}.max_score", node["max_score"]),
            direction=direction,
            bands=bands,
        )

    def _categorical_table(self, label: str, node: dict[str, Any]) -> CategoricalTable:
        options = {
            str(key): CategoricalOption(
                score=self._decimal(f"{label}.options.{key}.score", opt["score"]),
                label=str(opt["label"]),
            )
            for key, opt in node["options"].items()
        }
        return CategoricalTable(
            metric=label,
            max_score=self._decimal(f"{label}.max_score", node["max_score"]),
            options=options,
        )

    def _entry_barrier(self, node: dict[str, Any]) -> EntryBarrierConfig:
        return EntryBarrierConfig(
            max_score=self._decimal("entry_barrier.max_score", node["max_score"]),
            regulatory_points=self._decimal(
                "entry_barrier.regulatory_points", node["regulatory_points"]
            ),
            capital_intensity_normal_points=self._decimal(
                "entry_barrier.capital_intensity_normal_points",
                node["capital_intensity_normal_points"],
            ),
            capital_intensity_extreme_points=self._decimal(
                "entry_barrier.capital_intensity_extreme_points",
                node["capital_intensity_extreme_points"],
            ),
            network_effect_points=self._decimal(
                "entry_barrier.network_effect_points", node["network_effect_points"]
            ),
        )

    def _risk_config(self, node: dict[str, Any]) -> RiskConfig:
        return RiskConfig(
            base_score=self._decimal("risk.base_score", node["base_score"]),
            category_caps={
                str(reason): self._decimal(f"risk.category_caps.{reason}", cap)
                for reason, cap in node["category_caps"].items()
            },
            undefined_category_cap=self._decimal(
                "risk.undefined_category_cap", node["undefined_category_cap"]
            ),
        )
