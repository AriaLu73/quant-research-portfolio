# ESU6 MBO -> 1-second midprice ACF/PACF
#
# IMPORTANT
# ---------
# This file documents the logic of the original exploratory experiment.
# The raw ~1.4 GB Databento MBO CSV is not included in the repository, and
# the exact local schema from the original run is not available here.
# Map the column names below to your Databento export before running.
#
# Original exploratory output used ~15,542 reconstructed seconds because
# the reconstruction was interrupted before the full file completed.

options(stringsAsFactors = FALSE)
dir.create("figures", showWarnings = FALSE)

mbo_path <- Sys.getenv("ES_MBO_CSV")
if (mbo_path == "") {
  stop("Set ES_MBO_CSV to the local Databento MBO CSV path.")
}

# For a very large file, data.table::fread is strongly recommended.
if (!requireNamespace("data.table", quietly = TRUE)) {
  stop("Install data.table first: install.packages('data.table')")
}

x <- data.table::fread(mbo_path)

# ---- Schema mapping -------------------------------------------------------
# Adjust these names to match your Databento CSV export.
# Typical fields needed by the reconstruction are:
#   timestamp, action, side, price, size, order_id
#
# The exact event semantics must follow the schema of the source export.
required <- c("ts_event", "action", "side", "price", "size", "order_id")
missing_cols <- setdiff(required, names(x))
if (length(missing_cols) > 0) {
  stop(
    "Map these placeholder fields to your Databento schema: ",
    paste(missing_cols, collapse = ", ")
  )
}

# ---- Book reconstruction skeleton ---------------------------------------
# The original experiment maintained order state by order_id and obtained
# best bid / best ask after updates. This implementation is intentionally
# explicit rather than pretending the unavailable original script is exact.

book <- new.env(hash = TRUE, parent = emptyenv())

best_bid <- NA_real_
best_ask <- NA_real_

out_ts <- vector("numeric", nrow(x))
out_mid <- vector("numeric", nrow(x))
out_n <- 0L

# Helper to recompute BBO from active orders.
# This is simple and transparent, but not optimized for a 1.4 GB production run.
recompute_bbo <- function(book_env) {
  ids <- ls(book_env, all.names = TRUE)
  if (length(ids) == 0) return(c(NA_real_, NA_real_))

  orders <- lapply(ids, function(id) get(id, envir = book_env, inherits = FALSE))
  sides <- vapply(orders, `[[`, character(1), "side")
  prices <- vapply(orders, `[[`, numeric(1), "price")
  sizes <- vapply(orders, `[[`, numeric(1), "size")

  active <- sizes > 0
  sides <- sides[active]
  prices <- prices[active]

  bids <- prices[sides %in% c("B", "bid", "Bid")]
  asks <- prices[sides %in% c("A", "ask", "Ask")]

  c(
    if (length(bids)) max(bids) else NA_real_,
    if (length(asks)) min(asks) else NA_real_
  )
}

for (i in seq_len(nrow(x))) {
  id <- as.character(x$order_id[i])
  action <- as.character(x$action[i])

  # Map action codes to the semantics in your export.
  # The common conceptual cases are add / modify / cancel / trade / clear.
  if (action %in% c("A", "add", "Add")) {
    assign(
      id,
      list(
        side = as.character(x$side[i]),
        price = as.numeric(x$price[i]),
        size = as.numeric(x$size[i])
      ),
      envir = book
    )
  } else if (action %in% c("M", "modify", "Modify")) {
    if (exists(id, envir = book, inherits = FALSE)) {
      o <- get(id, envir = book, inherits = FALSE)
      o$price <- as.numeric(x$price[i])
      o$size <- as.numeric(x$size[i])
      assign(id, o, envir = book)
    }
  } else if (action %in% c("C", "cancel", "Cancel", "D", "delete", "Delete")) {
    if (exists(id, envir = book, inherits = FALSE)) {
      rm(list = id, envir = book)
    }
  }

  bbo <- recompute_bbo(book)
  best_bid <- bbo[1]
  best_ask <- bbo[2]

  if (is.finite(best_bid) && is.finite(best_ask) && best_bid <= best_ask) {
    out_n <- out_n + 1L
    out_ts[out_n] <- as.numeric(x$ts_event[i])
    out_mid[out_n] <- (best_bid + best_ask) / 2
  }
}

mid_events <- data.frame(
  ts_event = out_ts[seq_len(out_n)],
  mid = out_mid[seq_len(out_n)]
)

# ---- Convert to 1-second series ------------------------------------------
# ts_event may be integer nanoseconds or another Databento timestamp format.
# Adjust the conversion below if your exported ts_event is already POSIXct.

if (inherits(x$ts_event, "POSIXct")) {
  mid_events$sec <- as.POSIXct(mid_events$ts_event, origin = "1970-01-01", tz = "UTC")
  mid_events$sec <- as.POSIXct(floor(as.numeric(mid_events$sec)), origin = "1970-01-01", tz = "UTC")
} else {
  # Assumes nanoseconds since Unix epoch.
  mid_events$sec <- as.POSIXct(floor(mid_events$ts_event / 1e9), origin = "1970-01-01", tz = "UTC")
}

# Last observed midprice in each second.
mid_1s <- aggregate(mid ~ sec, data = mid_events, FUN = tail, 1)
mid_1s <- mid_1s[order(mid_1s$sec), ]

# IMPORTANT: do not bridge discontinuous segments in a rigorous rerun.
# The original exploratory construction may have concatenated segments.
dmid <- diff(mid_1s$mid)
dmid <- dmid[is.finite(dmid)]

cat("1-second mid observations:", nrow(mid_1s), "\n")
cat("ACF(1):", acf(dmid, plot = FALSE, lag.max = 1)$acf[2], "\n")

png("figures/es_midprice.png", width = 1400, height = 800)
plot(mid_1s$sec, mid_1s$mid, type = "l", xlab = "Time", ylab = "Midprice",
     main = "ESU6 reconstructed 1-second midprice")
dev.off()

png("figures/es_acf.png", width = 1400, height = 800)
acf(dmid, lag.max = 40, main = "ESU6 1-second midprice-difference ACF")
dev.off()

png("figures/es_pacf.png", width = 1400, height = 800)
pacf(dmid, lag.max = 40, main = "ESU6 1-second midprice-difference PACF")
dev.off()

# Original exploratory visual estimates:
# ACF(1)  ~ -0.14
# PACF(1) ~ -0.14
# PACF(2) ~ -0.04
