# MULTI-ASSET / MULTI-TIMEFRAME — liquidity-grab spec v2 across 7 instruments x 6 TFs

Generated 2026-07-22 by `multi_asset.py`. Instruments: XAUUSD, EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF (Dukascopy M1, volume>0 validated, 2015-12 → 2026-07-21). Execution TFs: 1m/5m/15m/30m/1h/4h resampled in NY tz. Config: literal spec v2 (fake-out-extreme SL, body≥25% signal candle, 2 full SLs per zone, T1 = recent swing, 80/20 BE runner to session end) + an rr5-target variant; eval 2016+, train ≤2022 / valid ≥2023; house all-in costs (USDJPY/AUDUSD estimated, documented in the script) with 0× and 2× stress. 252 runs total.

## Average R per trade — spec v2, swing T1, house cost

```
tf        1      5      15     30     60     240
pair                                            
AUDUSD -0.124 -0.044 -0.042 -0.057 -0.076 -0.180
EURUSD -0.086 -0.062 -0.064 -0.039 -0.034 -0.081
GBPUSD -0.089 -0.063 -0.060 -0.066 -0.017 -0.080
USDCAD -0.196 -0.149 -0.081 -0.076 -0.067 -0.195
USDCHF -0.259 -0.195 -0.183 -0.119 -0.099 -0.119
USDJPY -0.197 -0.079 -0.021 -0.054 -0.086  0.015
XAUUSD -0.101 -0.064 -0.056 -0.066 -0.097 -0.152
```

## Validation (2023+) net R — spec v2, swing T1

```
tf        1      5      15    30    60    240
pair                                         
AUDUSD -146.4   28.5   22.0   7.8   7.5 -10.8
EURUSD -147.2  -91.7  -70.1 -52.3   3.2   3.2
GBPUSD -359.2  -88.4  -41.0 -49.0  -4.3  -1.7
USDCAD -103.1 -109.3  -53.0 -58.4 -36.5 -19.4
USDCHF -308.5 -201.9 -172.8 -72.9 -31.8   7.9
USDJPY -165.2  -79.3   16.5 -38.2 -32.8  12.1
XAUUSD -230.0 -113.4  -61.6 -16.5 -43.5  -5.1
```

## rr5-target variant, avg R per trade

```
tf        1      5      15     30     60     240
pair                                            
AUDUSD -0.154 -0.041 -0.000 -0.052 -0.048 -0.203
EURUSD -0.085 -0.067 -0.040 -0.019 -0.034 -0.073
GBPUSD -0.132 -0.088 -0.053 -0.045 -0.026 -0.095
USDCAD -0.228 -0.138 -0.058 -0.081 -0.090 -0.203
USDCHF -0.228 -0.191 -0.191 -0.137 -0.127 -0.109
USDJPY -0.168 -0.049  0.001 -0.040 -0.070  0.042
XAUUSD -0.106 -0.028 -0.024 -0.058 -0.078 -0.165
```

## Frictionless (0x cost) avg R — is there any raw edge?

```
tf        1      5      15     30     60     240
pair                                            
AUDUSD  0.382  0.206  0.099  0.045 -0.009 -0.142
EURUSD  0.270  0.108  0.042  0.034  0.018 -0.055
GBPUSD  0.249  0.111  0.035  0.006  0.031 -0.049
USDCAD  0.418  0.102  0.074  0.050  0.041 -0.149
USDCHF  0.191  0.021 -0.049 -0.022 -0.026 -0.078
USDJPY  0.162  0.113  0.097  0.031 -0.026  0.051
XAUUSD  0.180  0.086  0.034 -0.000 -0.051 -0.128
```

## Findings

- **Every pair/TF cell is negative on average at house cost** (sole exception USDJPY H4, +0.015R on n=253 — and its train side is -0.049R, so it fails honest selection). Cells positive in BOTH train and valid with n≥100: **0 of 84** (swing) and **0** including the rr5 variant.
- **Higher timeframes are less bad, never good**: win rate climbs from ~13% (M1) to ~37% (H1) as the signal candle widens and costs shrink relative to the stop, and avg R improves monotonically toward H1 on most pairs (e.g. GBPUSD −0.089 → −0.017) — then deteriorates again at H4 where a 17:00-anchored session leaves only ~6 bars to work with.
- The pattern replicates across all six FX majors exactly as on gold: the previous-day sweep-reversal fires constantly, offers big planned RR, and hits its target far too rarely to pay for the losers, in every market tested.
- Frictionless table shows the residual raw edge is small and mostly ≤2022 wherever it exists at all; costs at realistic levels erase it everywhere.

Top 8 cells by avg R (all costs=1x), for the record:

```
  pair  tf    t1    n       wr       avg    tr_avg    va_avg
USDJPY 240   rr5  253 0.454545  0.041578 -0.011820  0.149010
USDJPY 240 swing  253 0.450593  0.015189 -0.048736  0.143799
USDJPY  15   rr5 2049 0.269400  0.000744 -0.034447  0.057998
AUDUSD  15   rr5 1528 0.265052 -0.000274 -0.077094  0.085257
GBPUSD  60 swing 1474 0.406377 -0.016642 -0.022873 -0.007333
EURUSD  30   rr5 2622 0.332571 -0.018658 -0.003440 -0.047192
USDJPY  15 swing 2257 0.355782 -0.020863 -0.045535  0.019215
XAUUSD  15   rr5 3158 0.289740 -0.024239 -0.039906  0.006334
```

**Verdict: the strategy is unprofitable on every instrument and every timeframe tested.** Combined with the 1,024 XAUUSD configurations from the earlier scans, this closes the question: the mechanical rules have no deployable edge anywhere in this universe.
