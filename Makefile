# Asset build orchestration for the self-hosted HTMX + Tailwind (v4) frontend.
# No Node.js required: Tailwind ships as a single standalone binary in bin/.

.DEFAULT_GOAL := help
TAILWIND := ./bin/tailwindcss
CSS_IN := static/css/app.src.css
CSS_OUT := static/css/app.css

.PHONY: help install-assets build-assets watch-css

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

$(TAILWIND):
	./scripts/install_tailwind.sh

install-assets: $(TAILWIND) ## Fetch the Tailwind binary, vendor HTMX + Alpine + Inter fonts (pinned + SHA256-verified)
	./scripts/install_htmx.sh
	./scripts/install_alpine.sh
	./scripts/install_fonts.sh

build-assets: $(TAILWIND) ## Compile the minified production CSS bundle
	$(TAILWIND) -i $(CSS_IN) -o $(CSS_OUT) --minify

watch-css: $(TAILWIND) ## Rebuild CSS on change (dev)
	$(TAILWIND) -i $(CSS_IN) -o $(CSS_OUT) --watch
