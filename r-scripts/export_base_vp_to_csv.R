#!/usr/bin/env Rscript
# Export INDEC Base_VP (RedatamX) to CSV via CRAN package redatamx.
#
# --- What the files in REDATAM_BASE_VP_DIR are (typical Censo 2022 VP bundle) ---
# *.rxdb  Dictionary / project file for Redatam X: entities, variables, types,
#         links to data. Opened with redatam_open().
# *.rbfx  Binary data files: compressed microdata fragments the engine reads with
#         the dictionary (naming like cpv2022-000.rbfx is usually shard/chunk "000").
#         They are not plain CSV; you do not "convert" them line-by-line in R.
#
# This script does NOT decode .rbfx directly. It uses the Redatam engine (same as
# opening the .rxdb) and runs SPC `freq <entity>.<variable>` for every variable so
# **all categories and their counts** in the base are exported (full marginal
# distributions). That is complete for validation/tabulados; it is **not** one row
# per person/housing unit (microdata/caso). For caso-level extracts use Redatam
# desktop / documented SPC LIST/TABLIST workflows or tools such as Redatam Converter.
#
# Data integrity:
# - Values returned by redatam_query are written as-is (no rounding, no recoding).
# - BASE_VP_TOT_OMIT=false (default) keeps total / na / mv rows the engine returns;
#   set BASE_VP_TOT_OMIT=true only if you want the package to drop those rows.
# - Stacked wide tables used to break because many FREQ outputs share the column
#   name `value`; wide_native now prefixes engine column names with the variable.
#
# Stacking (BASE_VP_STACK_STYLE):
#   narrow (default) — rows: entity, variable, value_code, value_label, count
#     (stable schema for DuckDB; every distinct code + label + count per variable).
#   wide_native — one block per variable with prefixed native column names, rbind_fill.
#
# Local snapshot: before the main OUT path, the same table is written under
#   <dirname(OUT)>/snapshots/<basename>_YYYYMMDD_HHMMSS.csv
#
# Optional raw per-variable extracts (exact engine columns, one file per variable):
#   BASE_VP_PER_VARIABLE_DIR=/path/to/folder
#   → <dir>/<entity>/<variable>.csv  (only redatam_query output; no stacking)
#
# Environment:
#   REDATAM_BASE_VP_DIR
#   BASE_VP_CSV_OUT
#   REDATAM_ENTITIES
#   BASE_VP_STACK_STYLE=narrow|wide_native
#   BASE_VP_TOT_OMIT=true|false   (default false)
#   BASE_VP_PER_VARIABLE_DIR      (optional)
#
# Requires: redatamx

REDATAM_DIR <- Sys.getenv(
  "REDATAM_BASE_VP_DIR",
  unset = "/Users/vlad/project/datasynk/data-local/redatam-db/bases_censo2022_RedatamX/Base_VP"
)

DEFAULT_OUT <- "/Users/vlad/project/datacyber/data-local/landing/indec/censo_2022/base_vp.csv"
OUT_CSV <- Sys.getenv("BASE_VP_CSV_OUT", unset = DEFAULT_OUT)

STACK_STYLE <- tolower(Sys.getenv("BASE_VP_STACK_STYLE", unset = "narrow"))
if (!STACK_STYLE %in% c("wide_native", "narrow")) {
  stop("BASE_VP_STACK_STYLE must be wide_native or narrow, not: ", STACK_STYLE)
}

env_bool <- function(nm, default) {
  v <- tolower(trimws(Sys.getenv(nm, unset = if (default) "true" else "false")))
  v %in% c("1", "true", "yes", "y")
}

# Default FALSE: do not drop total/na/mv rows or mask columns (preserve engine output).
TOT_OMIT <- env_bool("BASE_VP_TOT_OMIT", default = FALSE)

PER_VAR_DIR <- Sys.getenv("BASE_VP_PER_VARIABLE_DIR", unset = "")

if (!requireNamespace("redatamx", quietly = TRUE)) {
  install.packages("redatamx", repos = "https://cloud.r-project.org")
}
library(redatamx)

prefix_engine_cols <- function(df, entity, var) {
  if (is.null(df) || !is.data.frame(df) || ncol(df) < 1L) {
    return(df)
  }
  nm <- names(df)
  # Prefix avoids collisions (e.g. every FREQ has a `value` count column).
  safe <- gsub("[^A-Za-z0-9_.]+", "_", paste(entity, var, sep = "__"))
  names(df) <- paste0(safe, "__", nm)
  df
}

normalize_freq <- function(df, entity, var) {
  if (is.null(df) || !is.data.frame(df) || nrow(df) == 0L) {
    return(NULL)
  }
  cn <- names(df)
  val_col <- cn[grepl("_value$", cn)][1L]
  lab_col <- cn[grepl("_label$", cn)][1L]
  cnt_col <- if ("value" %in% cn) "value" else cn[length(cn)]

  data.frame(
    entity = entity,
    variable = var,
    value_code = if (!is.na(val_col)) df[[val_col]] else NA,
    value_label = if (!is.na(lab_col)) df[[lab_col]] else NA,
    count = df[[cnt_col]],
    stringsAsFactors = FALSE
  )
}

as_freq_block <- function(df, entity, var) {
  if (is.null(df) || !is.data.frame(df) || nrow(df) == 0L) {
    return(NULL)
  }
  df <- prefix_engine_cols(df, entity, var)
  cbind(
    data.frame(entity = entity, variable = var, stringsAsFactors = FALSE),
    df,
    stringsAsFactors = FALSE
  )
}

rbind_fill <- function(dfs) {
  if (!length(dfs)) {
    return(NULL)
  }
  all_names <- unique(unlist(lapply(dfs, names)))
  pad <- function(d) {
    miss <- setdiff(all_names, names(d))
    if (length(miss)) {
      d[miss] <- NA
    }
    d[, all_names, drop = FALSE]
  }
  do.call(rbind, lapply(dfs, pad))
}

write_snapshot_then_main <- function(out_df, main_path) {
  ddir <- dirname(main_path)
  if (!dir.exists(ddir)) {
    dir.create(ddir, recursive = TRUE, showWarnings = FALSE)
  }
  stamp <- format(Sys.time(), "%Y%m%d_%H%M%S")
  snap_root <- file.path(ddir, "snapshots")
  if (!dir.exists(snap_root)) {
    dir.create(snap_root, recursive = TRUE, showWarnings = FALSE)
  }
  base <- tools::file_path_sans_ext(basename(main_path))
  snap_path <- file.path(snap_root, paste0(base, "_", stamp, ".csv"))
  # quote=TRUE: protect commas in labels; numbers stay unquoted unless option changes.
  write.csv(out_df, snap_path, row.names = FALSE, fileEncoding = "UTF-8", quote = TRUE)
  message("Local snapshot (copy first): ", snap_path)
  write.csv(out_df, main_path, row.names = FALSE, fileEncoding = "UTF-8", quote = TRUE)
  message("Wrote main file: ", main_path)
}

main <- function() {
  if (!dir.exists(REDATAM_DIR)) {
    stop("Directory not found: ", REDATAM_DIR)
  }
  rxdb <- list.files(REDATAM_DIR, pattern = "\\.rxdb$", full.names = TRUE, ignore.case = TRUE)
  if (length(rxdb) < 1L) {
    stop("No .rxdb under ", REDATAM_DIR)
  }

  rbfx_n <- length(list.files(REDATAM_DIR, pattern = "\\.rbfx$", ignore.case = TRUE, full.names = TRUE))
  message("Opening ", rxdb[[1L]], " (", rbfx_n, " .rbfx data file(s) in folder)")
  dic <- redatam_open(rxdb[[1L]])
  on.exit(redatam_close(dic), add = TRUE)

  ents <- redatam_entities(dic)
  ent_names <- as.character(ents$name)
  filt <- Sys.getenv("REDATAM_ENTITIES", unset = "")
  if (nzchar(filt)) {
    keep <- strsplit(filt, ",", fixed = TRUE)[[1L]]
    keep <- trimws(keep)
    ent_names <- intersect(ent_names, keep)
    if (length(ent_names) == 0L) {
      stop("REDATAM_ENTITIES did not match any entity: ", filt)
    }
  }

  if (nzchar(PER_VAR_DIR)) {
    dir.create(PER_VAR_DIR, recursive = TRUE, showWarnings = FALSE)
    message("Per-variable CSVs → ", PER_VAR_DIR)
  }

  rows <- list()
  err_rows <- list()
  n_var <- 0L

  for (e in ent_names) {
    vars <- tryCatch(redatam_variables(dic, e), error = function(cond) {
      err_rows[[length(err_rows) + 1L]] <<- data.frame(
        entity = e,
        variable = NA_character_,
        error = conditionMessage(cond),
        stringsAsFactors = FALSE
      )
      return(NULL)
    })
    if (is.null(vars) || nrow(vars) < 1L) {
      next
    }
    vnames <- as.character(vars$name)
    for (v in vnames) {
      n_var <- n_var + 1L
      spc <- paste0("freq ", e, ".", v)
      df <- tryCatch(
        redatam_query(dic, spc, tot.omit = TOT_OMIT),
        error = function(cond) {
          err_rows[[length(err_rows) + 1L]] <<- data.frame(
            entity = e,
            variable = v,
            error = conditionMessage(cond),
            stringsAsFactors = FALSE
          )
          NULL
        }
      )

      if (nzchar(PER_VAR_DIR) && !is.null(df) && is.data.frame(df) && nrow(df) > 0L) {
        subd <- file.path(PER_VAR_DIR, e)
        dir.create(subd, recursive = TRUE, showWarnings = FALSE)
        pv <- file.path(subd, paste0(v, ".csv"))
        write.csv(df, pv, row.names = FALSE, fileEncoding = "UTF-8", quote = TRUE)
      }

      nd <- if (identical(STACK_STYLE, "narrow")) {
        normalize_freq(df, e, v)
      } else {
        as_freq_block(df, e, v)
      }
      if (!is.null(nd)) {
        rows[[length(rows) + 1L]] <- nd
      }
      if (n_var %% 10L == 0L) {
        message(sprintf("… %d variables processed", n_var))
      }
    }
  }

  if (length(rows) < 1L) {
    stop("No frequency tables produced.")
  }

  out <- if (identical(STACK_STYLE, "narrow")) {
    do.call(rbind, rows)
  } else {
    rbind_fill(rows)
  }
  rownames(out) <- NULL

  write_snapshot_then_main(out, OUT_CSV)
  message(
    "Done: ", nrow(out), " rows (stack=", STACK_STYLE, ", tot.omit=", TOT_OMIT, ")"
  )

  if (length(err_rows) > 0L) {
    efile <- sub("\\.csv$", "_errors.csv", OUT_CSV, ignore.case = TRUE)
    edf <- do.call(rbind, err_rows)
    write.csv(edf, efile, row.names = FALSE, fileEncoding = "UTF-8", quote = TRUE)
    message("Wrote ", nrow(edf), " error row(s) to ", efile)
  }
  invisible(OUT_CSV)
}

main()
