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
> Regenerate with `uv run python scripts/run_engine_replay.py`. Generated 2026-07-02T13:16:37+00:00.

## Summary

| metric | value |
|---|---|
| pairs (computed / skipped) | 124 (85 / 39) |
| MAE (modeled vs realized) | +3.25% |
| bias (modeled − realized) | -1.40% |
| sign hit-rate | 93% |
| Pearson r | 0.98 |
| regression spec | `ridge-std-v2|lookback=156|alpha=0.1|min_obs=40` |
| events version | `178033f6c134` |
| factor universe version | `3d07434f1346` |

## Per-pair results

Positive error = engine overstated the loss/gain; negative = understated.
`factors` is used (estimable at the vintage) / covered (non-NaN event returns).

| event | book | modeled | realized | error | factors | note |
|---|---|---|---|---|---|---|
| bnp-paribas-credit-2007 | msci_world | — | — | — | 17/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['ABBV', 'AVGO', 'META', 'TSLA', 'V'] |
| bnp-paribas-credit-2007 | us_tech_growth | — | — | — | 17/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['AVGO', 'META', 'TSLA'] |
| bnp-paribas-credit-2007 | defensive_mix | +3.50% | +3.39% | +0.11% | 17/17 | dropped: ACWI, HYG, MTUM, QUAL, SIZE, USMV, VLUE, XLC, XLRE |
| bnp-paribas-credit-2007 | japan_equity | — | — | — | 17/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['6098.T'] |
| lehman-gfc-2008 | msci_world | — | — | — | 18/0 | InsufficientHistoryError: Insufficient weekly history for beta estimation: V (n=25); minimum 40 non-NaN weeks overlapping the factor matrix required |
| lehman-gfc-2008 | us_tech_growth | — | — | — | 18/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['AVGO', 'META', 'TSLA'] |
| lehman-gfc-2008 | defensive_mix | -13.03% | -14.72% | +1.69% | 18/18 | dropped: ACWI, MTUM, QUAL, SIZE, USMV, VLUE, XLC, XLRE |
| lehman-gfc-2008 | japan_equity | — | — | — | 18/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['6098.T'] |
| gfc-trough-recovery-2009 | msci_world | — | — | — | 19/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['ABBV', 'AVGO', 'META', 'TSLA'] |
| gfc-trough-recovery-2009 | us_tech_growth | — | — | — | 19/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['AVGO', 'META', 'TSLA'] |
| gfc-trough-recovery-2009 | defensive_mix | +12.32% | +18.61% | -6.29% | 19/19 | dropped: MTUM, QUAL, SIZE, USMV, VLUE, XLC, XLRE |
| gfc-trough-recovery-2009 | japan_equity | — | — | — | 19/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['6098.T'] |
| euro-crisis-2010 | msci_world | — | — | — | 19/0 | InsufficientHistoryError: Insufficient weekly history for beta estimation: AVGO (n=37); minimum 40 non-NaN weeks overlapping the factor matrix required |
| euro-crisis-2010 | us_tech_growth | — | — | — | 19/0 | InsufficientHistoryError: Insufficient weekly history for beta estimation: AVGO (n=37); minimum 40 non-NaN weeks overlapping the factor matrix required |
| euro-crisis-2010 | defensive_mix | -5.57% | -2.24% | -3.33% | 19/19 | dropped: MTUM, QUAL, SIZE, USMV, VLUE, XLC, XLRE |
| euro-crisis-2010 | japan_equity | — | — | — | 19/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['6098.T'] |
| us-downgrade-2011 | msci_world | — | — | — | 19/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['ABBV', 'META'] |
| us-downgrade-2011 | us_tech_growth | — | — | — | 19/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['META'] |
| us-downgrade-2011 | defensive_mix | -3.86% | -3.68% | -0.18% | 19/19 | dropped: MTUM, QUAL, SIZE, USMV, VLUE, XLC, XLRE |
| us-downgrade-2011 | japan_equity | — | — | — | 19/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['6098.T'] |
| taper-tantrum-2013 | msci_world | — | — | — | 20/0 | InsufficientHistoryError: Insufficient weekly history for beta estimation: ABBV (n=0), META (n=33); minimum 40 non-NaN weeks overlapping the factor matrix required. n=0 usually means the market-data fetch returned no prices for the ticker (a transient provider failure) — retry the run |
| taper-tantrum-2013 | us_tech_growth | +4.55% | +12.57% | -8.03% | 20/20 | dropped: MTUM, QUAL, SIZE, VLUE, XLC, XLRE |
| taper-tantrum-2013 | defensive_mix | -3.09% | -1.79% | -1.30% | 20/20 | dropped: MTUM, QUAL, SIZE, VLUE, XLC, XLRE |
| taper-tantrum-2013 | japan_equity | — | — | — | 20/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['6098.T'] |
| oil-crash-2014 | msci_world | — | — | — | 24/0 | RuntimeError: All overlapping rows contained NaN factors; nothing to regress |
| oil-crash-2014 | us_tech_growth | +4.59% | +7.47% | -2.88% | 24/24 | dropped: XLC, XLRE |
| oil-crash-2014 | defensive_mix | +14.07% | +14.75% | -0.68% | 24/24 | dropped: XLC, XLRE |
| oil-crash-2014 | japan_equity | — | — | — | 24/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['6098.T'] |
| china-deval-2015 | msci_world | — | — | — | 24/0 | RuntimeError: All overlapping rows contained NaN factors; nothing to regress |
| china-deval-2015 | us_tech_growth | -5.58% | -3.32% | -2.25% | 24/24 | dropped: XLC, XLRE |
| china-deval-2015 | defensive_mix | -8.03% | -5.44% | -2.60% | 24/24 | dropped: XLC, XLRE |
| china-deval-2015 | japan_equity | -7.92% | -14.89% | +6.97% | 24/24 | dropped: XLC, XLRE |
| brexit-2016 | msci_world | +4.54% | +5.33% | -0.79% | 24/24 | dropped: XLC, XLRE |
| brexit-2016 | us_tech_growth | +5.89% | +6.58% | -0.69% | 24/24 | dropped: XLC, XLRE |
| brexit-2016 | defensive_mix | +3.75% | +5.22% | -1.47% | 24/24 | dropped: XLC, XLRE |
| brexit-2016 | japan_equity | -2.12% | +0.28% | -2.40% | 24/24 | dropped: XLC, XLRE |
| q4-trade-war-2018 | msci_world | -20.26% | -18.20% | -2.07% | 25/25 | dropped: XLC |
| q4-trade-war-2018 | us_tech_growth | -24.31% | -22.60% | -1.71% | 25/25 | dropped: XLC |
| q4-trade-war-2018 | defensive_mix | -7.46% | +0.65% | -8.11% | 25/25 | dropped: XLC |
| q4-trade-war-2018 | japan_equity | -10.15% | -18.54% | +8.39% | 25/25 | dropped: XLC |
| covid-crash-2020 | msci_world | -32.34% | -29.50% | -2.84% | 26/26 |  |
| covid-crash-2020 | us_tech_growth | -33.62% | -29.89% | -3.73% | 26/26 |  |
| covid-crash-2020 | defensive_mix | -19.41% | -20.05% | +0.64% | 26/26 |  |
| covid-crash-2020 | japan_equity | -29.44% | -27.55% | -1.88% | 26/26 |  |
| covid-liquidity-2020 | msci_world | +73.01% | +92.80% | -19.80% | 26/26 |  |
| covid-liquidity-2020 | us_tech_growth | +86.80% | +114.09% | -27.29% | 26/26 |  |
| covid-liquidity-2020 | defensive_mix | +28.31% | +33.67% | -5.36% | 26/26 |  |
| covid-liquidity-2020 | japan_equity | +34.35% | +46.02% | -11.67% | 26/26 |  |
| inflation-ukraine-2022 | msci_world | -29.85% | -25.29% | -4.55% | 26/26 |  |
| inflation-ukraine-2022 | us_tech_growth | -38.21% | -34.26% | -3.95% | 26/26 |  |
| inflation-ukraine-2022 | defensive_mix | -5.54% | +0.40% | -5.94% | 26/26 |  |
| inflation-ukraine-2022 | japan_equity | -12.81% | -21.39% | +8.58% | 26/26 |  |
| uk-gilt-crisis-2022 | msci_world | -0.85% | -1.12% | +0.27% | 26/26 |  |
| uk-gilt-crisis-2022 | us_tech_growth | -3.63% | -5.13% | +1.50% | 26/26 |  |
| uk-gilt-crisis-2022 | defensive_mix | +6.04% | +7.21% | -1.18% | 26/26 |  |
| uk-gilt-crisis-2022 | japan_equity | -0.27% | +1.37% | -1.64% | 26/26 |  |
| svb-banking-2023 | msci_world | +6.03% | +8.16% | -2.13% | 26/26 |  |
| svb-banking-2023 | us_tech_growth | +7.16% | +10.10% | -2.94% | 26/26 |  |
| svb-banking-2023 | defensive_mix | +8.00% | +9.05% | -1.05% | 26/26 |  |
| svb-banking-2023 | japan_equity | -1.80% | -0.41% | -1.39% | 26/26 |  |
| yen-carry-unwind-2024 | msci_world | -8.09% | -7.47% | -0.62% | 26/26 |  |
| yen-carry-unwind-2024 | us_tech_growth | -9.94% | -9.61% | -0.33% | 26/26 |  |
| yen-carry-unwind-2024 | defensive_mix | -0.95% | -0.43% | -0.52% | 26/26 |  |
| yen-carry-unwind-2024 | japan_equity | -3.01% | -19.33% | +16.32% | 26/26 |  |
| us-tariffs-2025 | msci_world | +7.82% | +9.38% | -1.57% | 26/26 |  |
| us-tariffs-2025 | us_tech_growth | +11.39% | +12.85% | -1.46% | 26/26 |  |
| us-tariffs-2025 | defensive_mix | -4.63% | -2.57% | -2.06% | 26/26 |  |
| us-tariffs-2025 | japan_equity | +11.38% | +11.08% | +0.30% | 26/26 |  |
| dotcom-crash-2000 | msci_world | — | — | — | 13/0 | InsufficientHistoryError: Insufficient weekly history for beta estimation: HSBC (n=34); minimum 40 non-NaN weeks overlapping the factor matrix required |
| dotcom-crash-2000 | us_tech_growth | — | — | — | 13/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['AVGO', 'CRM', 'GOOGL', 'META', 'NFLX', 'TSLA'] |
| dotcom-crash-2000 | defensive_mix | — | — | — | 13/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['MDLZ'] |
| dotcom-crash-2000 | japan_equity | — | — | — | 13/0 | InsufficientHistoryError: Insufficient weekly history for beta estimation: 4063.T (n=9), 6501.T (n=9), 6758.T (n=9), 6902.T (n=9), 7267.T (n=9), 8001.T (n=9), 8035.T (n=9), 8058.T (n=9), 8316.T (n=9), 9432.T (n=9), 9433.T (n=9), 9984.T (n=9); minimum 40 non-NaN weeks overlapping the factor matrix required |
| nine-eleven-2001 | msci_world | — | — | — | 14/0 | InsufficientHistoryError: Insufficient weekly history for beta estimation: ACN (n=7), MUFG (n=22); minimum 40 non-NaN weeks overlapping the factor matrix required |
| nine-eleven-2001 | us_tech_growth | — | — | — | 14/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['AVGO', 'CRM', 'GOOGL', 'META', 'NFLX', 'TSLA'] |
| nine-eleven-2001 | defensive_mix | — | — | — | 14/0 | InsufficientHistoryError: Insufficient weekly history for beta estimation: MDLZ (n=12); minimum 40 non-NaN weeks overlapping the factor matrix required |
| nine-eleven-2001 | japan_equity | — | — | — | 14/0 | InsufficientHistoryError: Insufficient weekly history for beta estimation: 6861.T (n=35); minimum 40 non-NaN weeks overlapping the factor matrix required |
| corporate-scandals-2002 | msci_world | — | — | — | 14/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['ABBV', 'AVGO', 'CRM', 'GOOGL', 'MA', 'META', 'NFLX', 'TSLA', 'V'] |
| corporate-scandals-2002 | us_tech_growth | — | — | — | 14/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['AVGO', 'CRM', 'GOOGL', 'META', 'NFLX', 'TSLA'] |
| corporate-scandals-2002 | defensive_mix | -22.45% | -23.57% | +1.12% | 14/14 | dropped: ACWI, EFA, GLD, HYG, MTUM, QUAL, SHY, SIZE, USMV, VLUE, XLC, XLRE |
| corporate-scandals-2002 | japan_equity | — | — | — | 14/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['6098.T', '8306.T'] |
| shanghai-correction-2007 | msci_world | — | — | — | 17/0 | InsufficientHistoryError: Insufficient weekly history for beta estimation: MA (n=39); minimum 40 non-NaN weeks overlapping the factor matrix required |
| shanghai-correction-2007 | us_tech_growth | — | — | — | 17/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['AVGO', 'META', 'TSLA'] |
| shanghai-correction-2007 | defensive_mix | -4.42% | -4.61% | +0.20% | 17/17 | dropped: ACWI, HYG, MTUM, QUAL, SIZE, USMV, VLUE, XLC, XLRE |
| shanghai-correction-2007 | japan_equity | — | — | — | 17/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['6098.T'] |
| japan-earthquake-2011 | msci_world | — | — | — | 19/0 | InsufficientHistoryError: Insufficient weekly history for beta estimation: TSLA (n=36); minimum 40 non-NaN weeks overlapping the factor matrix required |
| japan-earthquake-2011 | us_tech_growth | — | — | — | 19/0 | InsufficientHistoryError: Insufficient weekly history for beta estimation: TSLA (n=36); minimum 40 non-NaN weeks overlapping the factor matrix required |
| japan-earthquake-2011 | defensive_mix | -1.23% | -1.27% | +0.04% | 19/19 | dropped: MTUM, QUAL, SIZE, USMV, VLUE, XLC, XLRE |
| japan-earthquake-2011 | japan_equity | — | — | — | 19/0 | RuntimeError: yfinance returned no data for these portfolio tickers: ['6098.T'] |
| swiss-franc-unpeg-2015 | msci_world | — | — | — | 24/0 | RuntimeError: All overlapping rows contained NaN factors; nothing to regress |
| swiss-franc-unpeg-2015 | us_tech_growth | +2.64% | +4.34% | -1.70% | 24/24 | dropped: XLC, XLRE |
| swiss-franc-unpeg-2015 | defensive_mix | +2.10% | +1.98% | +0.12% | 24/24 | dropped: XLC, XLRE |
| swiss-franc-unpeg-2015 | japan_equity | — | — | — | 24/0 | InsufficientHistoryError: Insufficient weekly history for beta estimation: 6098.T (n=13); minimum 40 non-NaN weeks overlapping the factor matrix required |
| volmageddon-2018 | msci_world | -10.74% | -8.14% | -2.60% | 25/25 | dropped: XLC |
| volmageddon-2018 | us_tech_growth | -11.51% | -7.79% | -3.72% | 25/25 | dropped: XLC |
| volmageddon-2018 | defensive_mix | -7.22% | -9.68% | +2.47% | 25/25 | dropped: XLC |
| volmageddon-2018 | japan_equity | +2.28% | -6.02% | +8.30% | 25/25 | dropped: XLC |
| trade-war-reescalation-2019 | msci_world | -2.06% | -4.87% | +2.81% | 26/26 |  |
| trade-war-reescalation-2019 | us_tech_growth | -3.91% | -6.69% | +2.78% | 26/26 |  |
| trade-war-reescalation-2019 | defensive_mix | +9.67% | +3.30% | +6.37% | 26/26 |  |
| trade-war-reescalation-2019 | japan_equity | +1.92% | +1.11% | +0.81% | 26/26 |  |
| vaccine-rotation-2020 | msci_world | +4.63% | +6.07% | -1.43% | 26/26 |  |
| vaccine-rotation-2020 | us_tech_growth | +3.37% | +4.18% | -0.81% | 26/26 |  |
| vaccine-rotation-2020 | defensive_mix | +1.25% | +5.32% | -4.08% | 26/26 |  |
| vaccine-rotation-2020 | japan_equity | +10.08% | +13.67% | -3.59% | 26/26 |  |
| rates-tantrum-2021 | msci_world | -8.82% | -7.41% | -1.41% | 26/26 |  |
| rates-tantrum-2021 | us_tech_growth | -13.22% | -11.44% | -1.77% | 26/26 |  |
| rates-tantrum-2021 | defensive_mix | -2.17% | -3.68% | +1.52% | 26/26 |  |
| rates-tantrum-2021 | japan_equity | -5.60% | -2.47% | -3.13% | 26/26 |  |
| evergrande-2021 | msci_world | -3.94% | -4.82% | +0.89% | 26/26 |  |
| evergrande-2021 | us_tech_growth | -4.51% | -6.33% | +1.82% | 26/26 |  |
| evergrande-2021 | defensive_mix | -4.35% | -4.19% | -0.17% | 26/26 |  |
| evergrande-2021 | japan_equity | -3.46% | -6.13% | +2.67% | 26/26 |  |
| higher-for-longer-2023 | msci_world | -9.94% | -8.20% | -1.74% | 26/26 |  |
| higher-for-longer-2023 | us_tech_growth | -11.26% | -9.78% | -1.49% | 26/26 |  |
| higher-for-longer-2023 | defensive_mix | -4.86% | -0.67% | -4.19% | 26/26 |  |
| higher-for-longer-2023 | japan_equity | -16.85% | -7.66% | -9.19% | 26/26 |  |
| fed-pivot-rally-2023 | msci_world | +17.04% | +17.35% | -0.30% | 26/26 |  |
| fed-pivot-rally-2023 | us_tech_growth | +19.99% | +20.51% | -0.52% | 26/26 |  |
| fed-pivot-rally-2023 | defensive_mix | +7.06% | +5.80% | +1.26% | 26/26 |  |
| fed-pivot-rally-2023 | japan_equity | +13.99% | +13.44% | +0.55% | 26/26 |  |
| ai-capex-shock-2025 | msci_world | -2.64% | -2.06% | -0.58% | 26/26 |  |
| ai-capex-shock-2025 | us_tech_growth | -4.80% | -4.73% | -0.07% | 26/26 |  |
| ai-capex-shock-2025 | defensive_mix | +2.78% | +4.40% | -1.62% | 26/26 |  |
| ai-capex-shock-2025 | japan_equity | -4.24% | +0.53% | -4.77% | 26/26 |  |
