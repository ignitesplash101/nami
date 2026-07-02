# Engine replay validation

> **This is not a backtest and not a capability claim.** It measures one
> thing: given an event's REALIZED factor moves, how closely does the
> linear factor engine (vintage betas, no LLM anywhere) reproduce each
> sample book's realized buy-and-hold USD return over the same window?
> The residual is idiosyncratic/periphery return the factor model does
> not claim to capture, plus beta drift. Known caveats: the books are
> TODAY'S frozen cap-weight snapshots replayed onto historical windows
> (weights as of 2026-05-30 — point-in-time drift and
> survivorship bias), and both sides use dividend/split-adjusted closes.
>
> Regenerate with `uv run python scripts/run_engine_replay.py`. Generated 2026-07-02T11:48:50+00:00.

## Summary

| metric | value |
|---|---|
| pairs (computed / skipped) | 68 (48 / 20) |
| MAE (modeled vs realized) | +3.97% |
| bias (modeled − realized) | -2.13% |
| sign hit-rate | 90% |
| Pearson r | 0.98 |
| regression spec | `ridge-std-v2|lookback=156|alpha=0.1|min_obs=40` |
| events version | `c29595fc29c4` |
| factor universe version | `2907552c12a7` |

## Per-pair results

Positive error = engine overstated the loss/gain; negative = understated.
`factors` is used (estimable at the vintage) / covered (non-NaN event returns).

| event | book | modeled | realized | error | factors | note |
|---|---|---|---|---|---|---|
| bnp-paribas-credit-2007 | msci_world | — | — | — | 14/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['ABBV', 'AVGO', 'META', 'TSLA', 'V'] |
| bnp-paribas-credit-2007 | us_tech_growth | — | — | — | 14/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['AVGO', 'META', 'TSLA'] |
| bnp-paribas-credit-2007 | defensive_mix | +3.78% | +3.39% | +0.39% | 14/14 | dropped: ACWI, MTUM, QUAL, SIZE, USMV, VLUE, XLC, XLRE |
| bnp-paribas-credit-2007 | japan_equity | — | — | — | 14/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['6098.T'] |
| lehman-gfc-2008 | msci_world | — | — | — | 14/0 | InsufficientHistoryError: Insufficient weekly history for beta estimation: V (n=25); minimum 40 non-NaN weeks overlapping the factor matrix required |
| lehman-gfc-2008 | us_tech_growth | — | — | — | 14/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['AVGO', 'META', 'TSLA'] |
| lehman-gfc-2008 | defensive_mix | -14.29% | -14.72% | +0.43% | 14/14 | dropped: ACWI, MTUM, QUAL, SIZE, USMV, VLUE, XLC, XLRE |
| lehman-gfc-2008 | japan_equity | — | — | — | 14/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['6098.T'] |
| gfc-trough-recovery-2009 | msci_world | — | — | — | 15/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['ABBV', 'AVGO', 'META', 'TSLA'] |
| gfc-trough-recovery-2009 | us_tech_growth | — | — | — | 15/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['AVGO', 'META', 'TSLA'] |
| gfc-trough-recovery-2009 | defensive_mix | +13.33% | +18.61% | -5.29% | 15/15 | dropped: MTUM, QUAL, SIZE, USMV, VLUE, XLC, XLRE |
| gfc-trough-recovery-2009 | japan_equity | — | — | — | 15/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['6098.T'] |
| euro-crisis-2010 | msci_world | — | — | — | 15/0 | InsufficientHistoryError: Insufficient weekly history for beta estimation: AVGO (n=37); minimum 40 non-NaN weeks overlapping the factor matrix required |
| euro-crisis-2010 | us_tech_growth | — | — | — | 15/0 | InsufficientHistoryError: Insufficient weekly history for beta estimation: AVGO (n=37); minimum 40 non-NaN weeks overlapping the factor matrix required |
| euro-crisis-2010 | defensive_mix | -5.21% | -2.24% | -2.98% | 15/15 | dropped: MTUM, QUAL, SIZE, USMV, VLUE, XLC, XLRE |
| euro-crisis-2010 | japan_equity | — | — | — | 15/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['6098.T'] |
| us-downgrade-2011 | msci_world | — | — | — | 15/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['ABBV', 'META'] |
| us-downgrade-2011 | us_tech_growth | — | — | — | 15/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['META'] |
| us-downgrade-2011 | defensive_mix | -4.25% | -3.68% | -0.57% | 15/15 | dropped: MTUM, QUAL, SIZE, USMV, VLUE, XLC, XLRE |
| us-downgrade-2011 | japan_equity | — | — | — | 15/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['6098.T'] |
| taper-tantrum-2013 | msci_world | — | — | — | 16/0 | InsufficientHistoryError: Insufficient weekly history for beta estimation: ABBV (n=0), META (n=33); minimum 40 non-NaN weeks overlapping the factor matrix required. n=0 usually means the market-data fetch returned no prices for the ticker (a transient provider failure) — retry the run |
| taper-tantrum-2013 | us_tech_growth | +4.46% | +12.57% | -8.11% | 16/16 | dropped: MTUM, QUAL, SIZE, VLUE, XLC, XLRE |
| taper-tantrum-2013 | defensive_mix | -3.24% | -1.79% | -1.46% | 16/16 | dropped: MTUM, QUAL, SIZE, VLUE, XLC, XLRE |
| taper-tantrum-2013 | japan_equity | — | — | — | 16/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['6098.T'] |
| oil-crash-2014 | msci_world | — | — | — | 20/0 | RuntimeError: All overlapping rows contained NaN factors; nothing to regress |
| oil-crash-2014 | us_tech_growth | +4.10% | +7.47% | -3.37% | 20/20 | dropped: XLC, XLRE |
| oil-crash-2014 | defensive_mix | +10.93% | +14.75% | -3.82% | 20/20 | dropped: XLC, XLRE |
| oil-crash-2014 | japan_equity | — | — | — | 20/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['6098.T'] |
| china-deval-2015 | msci_world | — | — | — | 20/0 | RuntimeError: All overlapping rows contained NaN factors; nothing to regress |
| china-deval-2015 | us_tech_growth | -5.21% | -3.32% | -1.88% | 20/20 | dropped: XLC, XLRE |
| china-deval-2015 | defensive_mix | -8.25% | -5.44% | -2.81% | 20/20 | dropped: XLC, XLRE |
| china-deval-2015 | japan_equity | -8.53% | -14.89% | +6.36% | 20/20 | dropped: XLC, XLRE |
| brexit-2016 | msci_world | +4.05% | +5.33% | -1.29% | 20/20 | dropped: XLC, XLRE |
| brexit-2016 | us_tech_growth | +5.03% | +6.58% | -1.56% | 20/20 | dropped: XLC, XLRE |
| brexit-2016 | defensive_mix | +4.00% | +5.22% | -1.22% | 20/20 | dropped: XLC, XLRE |
| brexit-2016 | japan_equity | -0.59% | +0.28% | -0.87% | 20/20 | dropped: XLC, XLRE |
| q4-trade-war-2018 | msci_world | -19.64% | -18.20% | -1.45% | 21/21 | dropped: XLC |
| q4-trade-war-2018 | us_tech_growth | -23.68% | -22.60% | -1.08% | 21/21 | dropped: XLC |
| q4-trade-war-2018 | defensive_mix | -6.19% | +0.65% | -6.83% | 21/21 | dropped: XLC |
| q4-trade-war-2018 | japan_equity | -9.65% | -18.54% | +8.90% | 21/21 | dropped: XLC |
| covid-crash-2020 | msci_world | -30.55% | -29.50% | -1.05% | 22/22 |  |
| covid-crash-2020 | us_tech_growth | -31.26% | -29.89% | -1.37% | 22/22 |  |
| covid-crash-2020 | defensive_mix | -19.33% | -20.05% | +0.72% | 22/22 |  |
| covid-crash-2020 | japan_equity | -29.16% | -27.55% | -1.61% | 22/22 |  |
| covid-liquidity-2020 | msci_world | +70.78% | +92.80% | -22.02% | 22/22 |  |
| covid-liquidity-2020 | us_tech_growth | +83.83% | +114.09% | -30.27% | 22/22 |  |
| covid-liquidity-2020 | defensive_mix | +26.25% | +33.67% | -7.42% | 22/22 |  |
| covid-liquidity-2020 | japan_equity | +33.82% | +46.02% | -12.20% | 22/22 |  |
| inflation-ukraine-2022 | msci_world | -29.47% | -25.29% | -4.17% | 22/22 |  |
| inflation-ukraine-2022 | us_tech_growth | -37.84% | -34.26% | -3.58% | 22/22 |  |
| inflation-ukraine-2022 | defensive_mix | -3.72% | +0.40% | -4.12% | 22/22 |  |
| inflation-ukraine-2022 | japan_equity | -14.84% | -21.39% | +6.55% | 22/22 |  |
| uk-gilt-crisis-2022 | msci_world | -0.68% | -1.12% | +0.44% | 22/22 |  |
| uk-gilt-crisis-2022 | us_tech_growth | -3.30% | -5.13% | +1.83% | 22/22 |  |
| uk-gilt-crisis-2022 | defensive_mix | +6.44% | +7.21% | -0.78% | 22/22 |  |
| uk-gilt-crisis-2022 | japan_equity | -0.41% | +1.37% | -1.78% | 22/22 |  |
| svb-banking-2023 | msci_world | +7.56% | +8.16% | -0.60% | 22/22 |  |
| svb-banking-2023 | us_tech_growth | +9.43% | +10.10% | -0.67% | 22/22 |  |
| svb-banking-2023 | defensive_mix | +7.39% | +9.05% | -1.66% | 22/22 |  |
| svb-banking-2023 | japan_equity | +1.14% | -0.41% | +1.54% | 22/22 |  |
| yen-carry-unwind-2024 | msci_world | -7.92% | -7.47% | -0.45% | 22/22 |  |
| yen-carry-unwind-2024 | us_tech_growth | -9.75% | -9.61% | -0.13% | 22/22 |  |
| yen-carry-unwind-2024 | defensive_mix | -1.11% | -0.43% | -0.68% | 22/22 |  |
| yen-carry-unwind-2024 | japan_equity | -2.21% | -19.33% | +17.12% | 22/22 |  |
| us-tariffs-2025 | msci_world | +7.67% | +9.38% | -1.71% | 22/22 |  |
| us-tariffs-2025 | us_tech_growth | +11.73% | +12.85% | -1.12% | 22/22 |  |
| us-tariffs-2025 | defensive_mix | -5.31% | -2.57% | -2.75% | 22/22 |  |
| us-tariffs-2025 | japan_equity | +9.47% | +11.08% | -1.62% | 22/22 |  |
