// A literal entity reference used as an ordinary `==` operand (not a scope constraint or an
// `in`/`is` target) — as sales_orgs does with `principal.job == Job::"internal"`. cedarpy's
// EST represents this as {"Value": {"__entity": {...}}}, which must render to Cedar's
// canonical "Type::\"id\"" string, not pass through as an unconverted nested dict.
permit (principal, action, resource)
when { principal.job == Job::"internal" };
