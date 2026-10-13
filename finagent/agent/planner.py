def validate_plan(plan, known):
    errs = []
    for comp in plan.companies:
        info = next(
            (v for k, v in known.items() if getattr(k, "cik", None) == comp.cik),
            None,
        )
        if info is None:
            errs.append(f"unresolved company {comp.ticker}")
            continue
        concepts = info if isinstance(info, set) else info.get("concepts", set())
        for li in plan.line_items:
            if li.kind == "raw":
                if not any(c in concepts for c in li.concepts):
                    errs.append(f"{comp.ticker}: concept unavailable for {li.alias}")
        frames = known.get("frames", set())
        if plan.periods.type == "last_n_quarters" and not frames:
            errs.append(f"{comp.ticker}: no quarterly frames available")
    return errs
