# BTCUSDT split-sample robustness check
# Assumes btc and returns can be recreated from 01_btc_download_and_acf.R.

source("R/01_btc_download_and_acf.R")

n <- length(returns)
cut <- floor(n / 2)

r_first <- returns[1:cut]
r_last <- returns[(cut + 1):n]

acf1_first <- acf(r_first, plot = FALSE, lag.max = 1)$acf[2]
acf1_last <- acf(r_last, plot = FALSE, lag.max = 1)$acf[2]

cat(sprintf("First half ACF(1): %.4f\n", acf1_first))
cat(sprintf("Last half ACF(1):  %.4f\n", acf1_last))

# The original exploratory run produced approximately:
# first 12h: +0.1620
# last 12h:  +0.1492

png("figures/btc_split_acf_2026-10-20.png", width = 1400, height = 800)
par(mfrow = c(1, 2))
acf(r_first, lag.max = 30, main = sprintf("First half | ACF(1)=%.4f", acf1_first))
acf(r_last, lag.max = 30, main = sprintf("Last half | ACF(1)=%.4f", acf1_last))
par(mfrow = c(1, 1))
dev.off()
