#!/usr/bin/env python3
"""Pre-warm paper search cache for BestExamHelp-heavy subjects."""

from __future__ import annotations

import argparse
from datetime import datetime
from typing import Iterable, List

from Utils.sources_manager import PaperSourceManager


def parse_csv(value: str) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for token in str(value or "").split(","):
        item = token.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def parse_years(value: str) -> List[str]:
    text = str(value or "").strip()
    if not text:
        current = datetime.now().year % 100
        return [f"{yy:02d}" for yy in range(max(0, current - 2), current + 1)]
    if "-" in text:
        left, right = (part.strip() for part in text.split("-", 1))
        if left.isdigit() and right.isdigit():
            start = int(left)
            end = int(right)
            if start <= end:
                return [f"{year:02d}" for year in range(start, end + 1)]
    return [token.zfill(2)[-2:] for token in parse_csv(text) if token.strip().isdigit()]


def expand_components(papers: Iterable[str], variants: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for paper in papers:
        p = str(paper or "").strip()
        if not p or not p.isdigit():
            continue
        for variant in variants:
            v = str(variant or "").strip()
            if not v or not v.isdigit():
                continue
            component = f"{p}{v}"
            if component in seen:
                continue
            seen.add(component)
            out.append(component)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-warm PaperSourceManager cache for BestExamHelp subjects.")
    parser.add_argument(
        "--subjects",
        default=",".join(sorted(PaperSourceManager.BESTEXAMHELP_IGCSE_CODES)),
        help="Comma-separated subject codes (default: all known BestExamHelp IGCSE codes).",
    )
    parser.add_argument("--series", default="MJ,ON,FM", help="Comma-separated series codes.")
    parser.add_argument("--years", default="", help="Year list or range in YY format, e.g. 22-24 or 23,24.")
    parser.add_argument("--papers", default="1,2,3,4,5,6", help="Comma-separated base paper numbers.")
    parser.add_argument("--variants", default="1,2,3", help="Comma-separated component variants.")
    parser.add_argument("--types", default="QP,MS,GT", help="Comma-separated doc types to request.")
    args = parser.parse_args()

    subjects = [code for code in parse_csv(args.subjects) if code.isdigit() and len(code) == 4]
    series_list = [token.upper() for token in parse_csv(args.series)]
    years = parse_years(args.years)
    papers = [token for token in parse_csv(args.papers) if token.isdigit()]
    variants = [token for token in parse_csv(args.variants) if token.isdigit()]
    doc_types = [token.upper() for token in parse_csv(args.types)]
    components = expand_components(papers, variants)

    if not subjects or not series_list or not years or not components or not doc_types:
        print("Invalid inputs. Nothing to pre-warm.")
        return 1

    total_queries = 0
    total_groups = 0
    for subject in subjects:
        for series in series_list:
            for year in years:
                series_component_map = {series: list(components)}
                groups = PaperSourceManager.search_papers_multi_source(
                    subject_code=subject,
                    series_list=[series],
                    components=list(components),
                    years=[year],
                    doc_types=list(doc_types),
                    fm_locked_variant=None,
                    series_component_map=series_component_map,
                    cancel_check=None,
                )
                total_queries += 1
                total_groups += len(groups)
                print(
                    f"subject={subject} series={series} year={year} "
                    f"components={len(components)} groups={len(groups)}"
                )

    print(f"Done. queries={total_queries} groups={total_groups}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
