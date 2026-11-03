# BTCUSDT 1-second autocorrelation experiment
# Date: 2026-10-20
# Source: Binance public historical data

options(stringsAsFactors = FALSE)

symbol <- "BTCUSDT"
interval <- "1s"
date <- "2026-10-20"

out_dir <- file.path("data", "btc")
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
dir.create("figures", showWarnings = FALSE)

zip_name <- sprintf("%s-%s-%s.zip", symbol, interval, date)
zip_path <- file.path(out_dir, zip_name)

url <- sprintf(
  "https://data.binance.vision/data/spot/daily/klines/%s/%s/%s",
  symbol, interval, zip_name
)

if (!file.exists(zip_path)) {
  message("Downloading: ", url)
  download.file(url, zip_path, mode = "wb", quiet = FALSE)
}

# Extract before read.csv(). This avoids compressed-connection seek errors.
extracted <- unzip(zip_path, exdir = out_dir)
csv_path <- extracted[grepl("\\.csv$", extracted, ignore.case = TRUE)][1]

if (is.na(csv_path) || !file.exists(csv_path)) {
  stop("CSV was not found after extracting the Binance archive.")
}

# Binance kline columns. Some historical files may contain no header.
cols <- c(
  "open_time", "open", "high", "low", "close", "volume",
  "close_time", "quote_asset_volume", "number_of_trades",
  "taker_buy_base_volume", "taker_buy_quote_volume", "ignore"
)

btc <- read.csv(csv_path, header = FALSE, col.names = cols)
btc$close <- as.numeric(btc$close)

# Keep valid observations only.
btc <- btc[is.finite(btc$close) & btc$close > 0, ]
returns <- diff(log(btc$close))
returns <- returns[is.finite(returns)]

cat("Observations:", nrow(btc), "\n")
cat("Return observations:", length(returns), "\n")
cat("ACF(1):", acf(returns, plot = FALSE, lag.max = 1)$acf[2], "\n")

png("figures/btc_price_2026-10-20.png", width = 1400, height = 800)
plot(
  btc$close,
  type = "l",
  xlab = "1-second observation",
  ylab = "BTCUSDT close",
  main = "BTCUSDT 1-second close | 2026-10-20"
)
dev.off()

png("figures/btc_acf_2026-10-20.png", width = 1400, height = 800)
acf(returns, lag.max = 40, main = "BTCUSDT 1-second log-return ACF")
dev.off()

png("figures/btc_pacf_2026-10-20.png", width = 1400, height = 800)
pacf(returns, lag.max = 40, main = "BTCUSDT 1-second log-return PACF")
dev.off()
