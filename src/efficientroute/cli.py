"""Command line entry point."""

from __future__ import annotations

import argparse

from . import pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="efficientroute")
    sub = parser.add_subparsers(dest="command", required=True)

    stage0 = sub.add_parser("stage0", help="extract and measure the Tbilisi network")
    stage0.add_argument(
        "--force-extract",
        action="store_true",
        help="re-read the PBF instead of reusing data/derived/00-extract.pkl.gz",
    )

    sub.add_parser("stage1", help="build and audit the turn-expanded graph L(G)")
    sub.add_parser("stage2", help="build the time and capture model, and estimate the campaign")
    stage5 = sub.add_parser("stage5", help="solve one route per driving day")
    stage5.add_argument(
        "--report-only", action="store_true",
        help="re-render reports/05-routes.md from the existing artifact",
    )
    sub.add_parser("stage4b", help="re-test variant D, dispose of the trapped mainlines")
    sub.add_parser(
        "stage4c",
        help="compare the re-zoned plan against the committed one",
    )
    stage4 = sub.add_parser("stage4", help="partition the chosen scope into shift-sized days")
    stage4.add_argument(
        "--report-only",
        action="store_true",
        help="re-render reports/04-zoning.md from the existing artifact",
    )
    stage3 = sub.add_parser(
        "stage3", help="bound the problem and build one constructive tour"
    )
    stage3.add_argument(
        "--report-only",
        action="store_true",
        help="re-render reports/03-bounds.md from the existing artifact, without re-solving",
    )
    sub.add_parser(
        "stage0b", help="measure the highway=service subtag split and scope scenarios"
    )

    args = parser.parse_args(argv)
    if args.command == "stage0":
        summary = pipeline.run(force_extract=args.force_extract)
        headline = summary["headline"]["required_traversal_km"]
        print(f"\nRequired traversal: {headline:,.1f} km")
        return 0
    if args.command == "stage0b":
        payload = pipeline.run_stage0b()
        for row in payload["variants"]:
            print(
                f"  {row['variant']}: {row['required_traversal_km']:>9,.1f} km required "
                f"({row['delta_required_km']:+,.1f})   |V(L)| {row.get('l_nodes', 0):,}"
            )
        return 0
    if args.command == "stage2":
        payload = pipeline.run_stage2()
        for row in payload["campaign"]["variants"]:
            print(
                f"  {row['variant']}: {row['required_km']:>9,.1f} km  "
                f"{row['capture_hours']:>7,.1f} capture h  {row['turn_hours']:>6,.1f} turn h  "
                f"{row['days']:>5.1f} days"
            )
        sweep = payload["campaign"]["sensitivity"]
        low, high = sweep[1]["days"], sweep[-1]["days"]
        print(f"\nCongestion sensitivity (variant A): {low:.1f} – {high:.1f} days")
        return 0
    if args.command == "stage5":
        if args.report_only:
            pipeline.rewrite_stage5_report()
            return 0
        payload = pipeline.run_stage5()
        t = payload["totals"]
        print(
            f"\n  {t['days']} days  {t['start_date']} → {t['finish_date']}  "
            f"{t['route_h']:,.1f} h driving  "
            f"(capture {t['capture_h']:,.1f} · deadhead {t['deadhead_h']:,.1f} · "
            f"turns {t['turn_h']:,.1f})  gap {t['optimality_gap'] * 100:.1f}%"
        )
        if t["days_over_window"]:
            print(f"  {t['days_over_window']} days exceed their window")
        return 0
    if args.command == "stage4c":
        payload = pipeline.run_stage4c()
        before, after = payload["before"], payload["after"]
        for label, row in (("committed", before), ("re-zoned ", after)):
            print(
                f"  {label}: {row['days']:>3} days  {row['total_h']:>6,.1f} h  "
                f"mean day {row['mean_day_h']:.2f} h  "
                f"over-window {row['over']}  splits {row['splits']}  → {row['finish']}"
            )
        delta = before["days"] - after["days"]
        print(
            f"  verdict: {'ADOPT' if delta > 0 and after['over'] == 0 else 'KEEP COMMITTED'}"
            f"  ({delta:+d} days, {after['total_h'] - before['total_h']:+,.1f} h)"
        )
        return 0
    if args.command == "stage4b":
        payload = pipeline.run_stage4b()
        for variant, rows in sorted(payload["decision_inputs"]["variants"].items()):
            for name, row in sorted(rows.items()):
                print(
                    f"  {variant} @ {name}: {row['days']:>3} days → {row['finish']}  "
                    f"margin {row['margin_days']:+4d} d  {'fits' if row['fits'] else 'MISSES'}"
                )
        return 0
    if args.command == "stage4":
        if args.report_only:
            pipeline.rewrite_stage4_report()
            return 0
        payload = pipeline.run_stage4()
        for name, block in sorted(payload["windows"].items()):
            campaign = block["campaign"]
            print(
                f"  {name}: {campaign['days']:>3} days  "
                f"{campaign['start_date']} → {campaign['finish_date']}  "
                f"{campaign['total_hours']:>6,.1f} h  "
                f"day {campaign['day_hours_min']:.2f}–{campaign['day_hours_max']:.2f} h "
                f"(sd {campaign['day_hours_stdev']:.2f})  "
                f"commute {campaign['commute_capture_h']:.1f} h"
            )
        return 0
    if args.command == "stage3":
        if args.report_only:
            pipeline.rewrite_stage3_report()
            return 0
        payload = pipeline.run_stage3()
        for row in payload["variants"]:
            print(
                f"  {row['variant']}: upper {row['total_h']:>7,.1f} h  "
                f"lower {row['lower_bound_h']:>7,.1f} h  gap {row['optimality_gap'] * 100:>5.1f}%  "
                f"deadhead {row['deadhead_pct_of_capture']:>5.1f}%  {row['days']:>5.1f} days"
            )
        return 0
    if args.command == "stage1":
        audit = pipeline.run_stage1()
        scc = audit["scc"]
        print(
            f"\nL(G): {audit['graph']['nodes']:,} nodes, {audit['graph']['edges']:,} manoeuvres; "
            f"largest SCC reaches {scc['share_of_required_km']:.2%} of required km"
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
