# FROM-SCRATCH DISCOVERY — new families, none present in the deployed bot

`discover_new.py` + `discover_new2.py`. Nine concept families designed to avoid every family in the owner's bot and research battery, run across 7 symbols (XAUUSD 2008–26, six majors 2016–26, Dukascopy M1-derived frames), 357 parameter cells total, all recorded. Protocol: selection on TRAIN only (gold ≤2023, FX ≤2022), untouched validation (gold ≥2024, FX ≥2023), house all-in costs with 2× stress on live cells, plateau = majority of a family's cells train-positive.

Families: ORB (session opening-range breakout), PULL (H1 EMA20-pullback in EMA200 trend), TSMOM (D1 extreme-break momentum with ATR trail), AFADE (Asia-midpoint reversion at London), HANDOFF (London→NY momentum carry), IBX (H4 inside-bar breakout), MR3 (D1 3-bar mean reversion with trend filter), RNGX (H4 range-expansion continuation), GAPF (weekend gap fade).

## Survivors (8 of 63 family×symbol combinations)

| symbol | family | params | n | WR | avg R | train | valid | maxDD | yrs+ | 2× avg |
|---|---|---|---|---|---|---|---|---|---|---|
| XAUUSD | TSMOM | 55-day break, 3×ATR trail, long | 57 | 49% | +0.914 | +27.2 | +24.9 | −3.0 | 13/19 | +0.569 |
| XAUUSD | PULL | EMA20 dip in EMA200 uptrend, rr3 | 1315 | 33% | +0.132 | +99.1 | +74.9 | −32.6 | 13/19 | +0.072 |
| XAUUSD | RNGX | H4 range≥2ATR close-strong, long rr3 | 458 | 43% | +0.250 | +88.2 | +26.2 | −20.2 | 15/19 | +0.199 |
| USDJPY | PULL | both sides, rr3 | 790 | 32% | +0.112 | +64.1 | +24.2 | −38.7 | 9/12 | +0.106 |
| USDJPY | TSMOM | 20-day break, long | 46 | 39% | +0.295 | +9.9 | +3.6 | −6.3 | 7/11 | +0.332 |
| USDJPY | MR3 | 3 down closes above SMA50, long rr2.5 | 48 | 58% | +0.341 | +8.5 | +7.8 | −3.0 | 7/11 | +0.221 |
| USDCHF | RNGX | H4 expansion continuation, both sides rr3 | 223 | 40% | +0.222 | +26.5 | +23.1 | −14.5 | 10/12 | +0.221 |
| USDCAD | TSMOM | 20-day break, long | 44 | 39% | +0.475 | +10.4 | +10.5 | −6.2 | 9/11 | +0.304 |

Per-symbol tally: XAUUSD 3, USDJPY 3, USDCHF 1, USDCAD 1, EURUSD 0, GBPUSD 0, AUDUSD 0.

## Honest caveats
- The three D1 TSMOM/MR3 cells have small samples (44–57 trades) — below the house n≥80 bar; treat as promising, not proven. The three large-sample results are XAUUSD PULL (1,315), XAUUSD RNGX (458), USDJPY PULL (790), plus USDCHF RNGX (223).
- XAUUSD PULL is holdout-heavy (valid avg +0.37 vs train +0.09): gold's 2024–26 melt-up flatters every long-dip family. Kinship disclosure: the owner's research watchlist had a different pullback formulation ("dip3", borderline); this EMA-touch formulation is new but the same market idea. RNGX is the two-sided H4 cousin of the owner's H1 short-only CRASH — same "expansion continues" physics, different TF/sides/instrument set.
- EURUSD, GBPUSD, AUDUSD: 0 survivors in 9 families × ~12 cells each. Every train-positive cell on these pairs failed validation or costs — fully consistent with the owner's prior 250-cell research ("FX fades die at true costs") and with our multi-asset scans. At retail all-in spreads these three pairs appear to have no harvestable edge in this concept space; anyone claiming otherwise should show a holdout.
- Multiplicity context: 8 passes from 357 cells with selection-on-train only. The strongest defense is family-level plateaus (all 8 passes come from families whose OTHER cells are also train-positive on that symbol) and cross-symbol replication (PULL passes on 2 symbols, TSMOM on 3, RNGX on 2).
