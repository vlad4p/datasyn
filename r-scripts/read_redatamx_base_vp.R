#!/usr/bin/env Rscript
# Read INDEC Censo 2022 RedatamX bundle (Base_VP: cpv2022.rxdb + cpv2022-*.rbfx)
# via CRAN package redatamx (RXDB + DICX).
#
# Requires: R + redatamx (downloads Redatam runtime at install time; see ?redatamx).

# -----------------------------------------------------------------------------
# Paths — override REDATAM_DIR if your tree differs.
# -----------------------------------------------------------------------------
REDATAM_DIR <- Sys.getenv(
  "REDATAM_BASE_VP_DIR",
  unset = "/Users/vlad/project/datasynk/data-local/redatam-db/bases_censo2022_RedatamX/Base_VP"
)

# -----------------------------------------------------------------------------
# Install redatamx from CRAN if missing
# -----------------------------------------------------------------------------
if (!requireNamespace("redatamx", quietly = TRUE)) {
  install.packages("redatamx", repos = "https://cloud.r-project.org")
}

library(redatamx)

main <- function() {
  if (!dir.exists(REDATAM_DIR)) {
    stop(
      "Directory does not exist: ", REDATAM_DIR, "\n",
      "Set environment variable REDATAM_BASE_VP_DIR or edit REDATAM_DIR in this script."
    )
  }

  rxdb <- list.files(REDATAM_DIR, pattern = "\\.rxdb$", ignore.case = TRUE, full.names = TRUE)
  if (length(rxdb) == 0L) {
    stop("No .rxdb dictionary found under: ", REDATAM_DIR)
  }
  if (length(rxdb) > 1L) {
    message("Multiple .rxdb files; using the first: ", rxdb[[1L]])
  }
  dict_path <- rxdb[[1L]]
  rbfx_n <- length(list.files(REDATAM_DIR, pattern = "\\.rbfx$", ignore.case = TRUE))
  message("Opening dictionary: ", dict_path, " (", rbfx_n, " .rbfx sibling file(s) in folder)")
  cat("redatam_version(): ", redatam_version(), "\n", sep = "")

  dic <- redatam_open(dict_path)
  on.exit(redatam_close(dic), add = TRUE)

  entities <- redatam_entities(dic)
  cat("\n--- Entities ---\n")
  print(entities)

  # Column name for entity label varies by version; take first character column or first column.
  entity_names <- character(0L)
  if (nrow(entities) > 0L) {
    if ("name" %in% names(entities)) {
      entity_names <- as.character(entities$name)
    } else {
      ch <- vapply(entities, is.character, logical(1L))
      if (any(ch)) {
        entity_names <- as.character(entities[[ which(ch)[1L] ]])
      } else {
        entity_names <- as.character(entities[[1L]])
      }
    }
  }

  for (en in entity_names) {
    cat("\n--- Variables: ", en, " ---\n", sep = "")
    print(redatam_variables(dic, en))
  }

  # Example SPC query — replace entity.variable with names from redatam_variables().
  # See ?redatam_query and Redatam SPC documentation.
  #
  # df <- redatam_query(dic, "freq <entity>.<variable>")
  # print(head(df))

  invisible(NULL)
}

main()
