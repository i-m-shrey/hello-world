# THE DEFINITIVE STRATEGY MATRIX — July 15, 2026

Sources: TZ-audit corrected re-runs, house-lab FX re-runs (fx_h1_backtest on
live_signals, true-UTC data), discovery studies 1-8 (discovery_ledger.csv, ~250
cells). 'n/t' = not testable in this cycle (pre-dates the cost-stress gate or
needs the owner's terminal). Capital = $100 / (monthly R x 1% risk).

| Strategy / Magic | Asset | TF | Status | n | tr/mo | WR% | R:R | avg R | Train R | Holdout R | 3x stress | Cap for $100/mo @1% |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| XAUUSD_S5 / 50001 | XAUUSD | M5 | Live | 745 | 13.3 | 45.0 | — | 0.036 | 16.3 | 10.8 | n/t (pre-gate) | $20,880 |
| XAUUSD_S6R / 60001 | XAUUSD | M5 | Live | 660 | 11.8 | 40.9 | — | 0.046 | 17.8 | 12.7 | n/t (pre-gate) | $18,445 |
| XAUUSD_S4 / 40001 | XAUUSD | M5 | Live — VOID, disable | 9 | 0.2 | — | — | 0.333 | -1.0 | 4.0 | n/t | $186,854 |
| XAUUSD_S3LO / 30001 | XAUUSD | M5 | Live — regime-young | 318 | 5.7 | 47.0 | — | 0.062 | 10.4 | 9.4 | Borderline (2x kills lifetime) | $28,403 |
| EURUSD_E / 80001 | EURUSD | H1 | Live | 475 | 2.5 | 31.2 | 2.43 | 0.196 | 55.5 | 37.5 | PASS (+0.171) | $20,193 |
| GBPUSD_E / 90001 | GBPUSD | H1 | Live | 425 | 2.3 | 28.9 | 2.43 | 0.134 | 38.5 | 18.5 | Borderline (+0.047) | $33,011 |
| USDCAD_A / 70001 | USDCAD | H1 | Live | 343 | 1.8 | 40.5 | 1.63 | 0.059 | 8.9 | 11.3 | Borderline (+0.036) | $92,899 |
| USDCHF_A / 71001 | USDCHF | H1 | Live | 109 | 0.6 | 46.8 | 1.77 | 0.215 | 13.5 | 9.9 | PASS (+0.216) | $80,222 |
| GBPUSD_P1 / 91001 | GBPUSD | H1 | Live | — | — | 49.0 | 2.00 | 0.125 | — | — | PASS (official 3x +43R) | — |
| EURUSD_P1_30 / 82001 | EURUSD | M30 | Live | — | — | — | 2.00 | — | — | — | Borderline (3x -> +7R) | — |
| USDCHF_P1 / 72101 | USDCHF | H1 | Live | — | — | — | 2.00 | 0.125 | 10.0 | 6.0 | Borderline (2x ok) | — |
| USDCHF_RSI30 / 72001 | USDCHF | M30 | Live | 80 | 0.8 | 52.0 | — | 0.245 | 12.4 | 7.2 | Borderline (feed-dependent) | $48,980 |
| GBPUSD_AVWAP / 58001 | GBPUSD | H1 | Live | — | — | — | — | — | — | — | n/t | — |
| XAUUSD_DONCH / 53001 | XAUUSD | H1 | Live (gate $250) | 895 | 4.0 | 33.0 | 3.00 | 0.144 | 53.9 | 74.8 | PASS (+0.092) | $17,225 |
| XAUUSD_MACROSS / 54001 | XAUUSD | H1 | Live (gate $250) | 439 | 2.0 | — | 3.00 | 0.124 | 37.8 | 16.7 | PASS (+0.133) | $40,782 |
| XAUUSD_CRASH / 57001 | XAUUSD | H1 | Live (insurance) | 610 | 2.7 | 37.0 | 2.00 | 0.076 | 60.1 | -14.1 | PASS (by design ho<0 in bulls) | $47,886 |
| XAUUSD_BOS / 59001 | XAUUSD | H1 | Live (gate $250) | 1691 | 7.6 | — | 5.00 | 0.161 | 186.4 | 86.7 | PASS (+0.085) | $8,154 |
| XAUUSD_STRAD / 52001 | XAUUSD | H1 | Live | 556 | 2.5 | — | — | 0.146 | 77.0 | 4.5 | PASS (official) | $27,348 |
| XAUUSD_H1A / 51001 | XAUUSD | H1 | Live | 233 | 1.0 | — | 2.00 | 0.109 | 18.0 | 7.5 | n/t (pre-gate) | $87,412 |
| SPX500_DONCH / 55001 | SPX500 | H1 | Live | 198 | 3.7 | — | 3.00 | 0.044 | 2.2 | 6.6 | Borderline (my feed FAIL; official cross-feed ok) | $61,983 |
| GER40_DONCH / 56001 | GER40 | H1 | Live (gate $300) | 200 | 3.7 | — | 3.00 | 0.220 | 18.2 | 25.7 | PASS (+0.153) | $12,273 |
| GER40_BOS / 59501 | GER40 | H1 | Live (gate $300) | 424 | 7.9 | — | 3.00 | 0.038 | 9.2 | 7.0 | Borderline (-0.029) | $33,515 |
| US30_DONCH / 55501 | US30 | H1 | Live (gate $600) | 181 | 3.4 | — | 3.00 | 0.151 | 16.5 | 10.8 | PASS (+0.133) | $19,758 |
| JPN225_DONCH / 55601 | JPN225 | H1 | Live (gate $800) | 202 | 3.7 | — | 3.00 | 0.153 | -5.9 | 36.8 | Borderline (train-neg my window) | $17,472 |
| HK50_MACROSS / 55701 | HK50 | H1 | Live (gate $800) | — | — | — | 3.00 | — | — | — | n/t | — |
| EURUSD_BOLL30 / 81001 | EURUSD | M30 | Benched (true cost) | — | — | — | 1.00 | — | — | — | Fail | — |
| EURUSD_BOLL15 / 83001 | EURUSD | M15 | Benched | 3037 | 13.7 | — | 1.00 | 0.056 | 163.8 | 6.5 | Fail (TZ-fix gutted holdout) | $13,053 |
| GBPUSD_BOLL15 / 92001 | GBPUSD | M15 | Benched — re-enable candidate | 5965 | 26.9 | — | 1.00 | 0.070 | 377.0 | 39.2 | PASS (official 3x) | $5,317 |
| USDCHF_BOLL15 / 73001 | USDCHF | M15 | Benched — keep benched | 5386 | 24.3 | — | 1.00 | 0.056 | 306.6 | -3.3 | Fail (holdout<0 TZ-fixed) | $7,360 |
| XAUUSD_DONCH_TR / 53101 | XAUUSD | H1 | Approved (built+verified) | 661 | 3.0 | 35.0 | 3.50 | 0.277 | 116.8 | 66.0 | PASS (+0.217) | $12,125 |
| XAUUSD_DONCH30_TR / 53201 | XAUUSD | M30 | Proposed | 1288 | 5.8 | 32.6 | 2.70 | 0.185 | 164.7 | 74.0 | PASS (+0.107) | $9,317 |
| XAUUSD_DONCH4H_TR / 53301 | XAUUSD | H4 | Proposed | 202 | 0.9 | 35.1 | 3.51 | 0.489 | 49.4 | 49.5 | PASS (+0.436) | $22,475 |
| XAUUSD_SDNY / 50201 | XAUUSD | H1 | Proposed (S6R-overlap check pending) | 196 | 0.9 | 36.2 | 2.35 | 0.217 | 33.8 | 8.8 | PASS (+0.156) | $52,196 |
| GER40_DONCH48_H4_TR / 56101 | GER40 | H4 | Proposed (2022+ grade) | 59 | 1.1 | — | — | 0.640 | 14.4 | 23.4 | PASS (+0.542) | $14,301 |
| US30_DONCH96_TR / 55801 | US30 | H1 | Proposed (2022+ grade) | 146 | 2.7 | — | — | 0.319 | 18.8 | 27.8 | PASS (+0.255) | $11,594 |
| VCX gold W96 | XAUUSD | H1 | Watchlist — 96% overlap w/ DONCH | 339 | 1.5 | — | 3.00 | 0.302 | 73.6 | 28.9 | PASS (+0.229) | $21,684 |
| MTF-DONCH N24 H4-gated | XAUUSD | H1 | Watchlist — holdout-heavy | 1025 | 4.6 | — | 3.00 | 0.143 | 48.1 | 98.0 | PASS (+0.095) | $15,146 |
| PULLBACK gold dip3 rr3 | XAUUSD | H1 | Watchlist — weak train | 1239 | 5.6 | — | 3.00 | 0.084 | 31.4 | 72.6 | Borderline (+0.036) | $21,331 |
| SPX500 DONCH96 trail3 | SPX500 | H1 | Watchlist — 3x fragile | 183 | 3.4 | — | — | 0.165 | 18.7 | 11.5 | Borderline (+0.006) | $17,884 |
| XAG D1 DONCH20 trail3 | XAGUSD | D1 | Watchlist — train-flat (+0.3R) | 77 | 0.4 | — | — | 0.187 | 0.3 | 14.1 | PASS (+0.156) | $129,176 |
| USDJPY DONCH96 trail4 | USDJPY | H1 | Watchlist — holdout-flat (+1.3R) | 641 | 3.3 | — | — | 0.189 | 120.1 | 1.3 | PASS (+0.117) | $15,931 |
| FX band/RSI fades — all pairs M15/M30/H1/H4/D1 | FX x7 | multi | Rejected | — | — | — | — | — | — | — | Fail | — |
| H4 liquidity-sweep fade x7 pairs | FX x7 | H4 | Rejected (6th sweep test) | — | — | — | — | — | — | — | Fail | — |
| A/E family cross-pair ports | EUR/GBP/CHF/CAD | H1 | Rejected (noise to negative) | — | — | — | — | — | — | — | Fail | — |
| Session-displacement: FX-style on GER40/US30/gold-London | idx+gold | M15/H1 | Rejected | — | — | — | — | — | — | — | Fail | — |
| XAGUSD H1/H4 trend+fade (all) | XAGUSD | H1/H4 | Rejected — costs | — | — | — | — | — | — | — | Fail | — |
| Regime routing (ER gate, both directions) | all | multi | Rejected — falsified | — | — | — | — | — | — | — | — | — |
| USD-basket gate on gold | XAUUSD | H1 | Rejected — train-negative | — | — | — | — | — | — | — | — | — |
| JPN225/HK50 trend adds; gold M15 trend | idx/gold | H1/H4/M15 | Rejected | — | — | — | — | — | — | — | Fail | — |

**Notes.** (1) Live gold-M5 rows show TZ-corrected numbers — S4 void, S6R roughly
halved vs its buggy-TZ validation. (2) FX-fade family rows depend on the live
spread audit: at 3.0-pip crosses every fade dies (RSI30 breaks even at ~2.3x its
assumed cost, i.e. ~2.3 pips all-in). (3) Index rows are 2022+ evidence grade.
(4) Capital figures use each strategy's OWN R/month; running the whole book on
shared capital stacks them (current corrected book ~3 R/mo -> ~$3,300; with the
approved+proposed slate ~4.3 R/mo -> ~$2,300).
