#!/usr/bin/env bash
# ==============================================================================
# CareerAgent Batch PDF Compiler & ATS 1-Page Verification
# ==============================================================================

set -e

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSIONS_DIR="$BASE_DIR/versions"

echo "======================================================================"
echo " Starting CareerAgent CV Batch Compilation (pdflatex)"
echo "======================================================================"

COMPILE_COUNT=0
ERROR_COUNT=0
PAGE_VIOLATION_COUNT=0

compile_file() {
    local tex_file="$1"
    local dir_name="$(dirname "$tex_file")"
    local base_name="$(basename "$tex_file" .tex)"
    local pdf_file="$dir_name/$base_name.pdf"
    
    echo -n "Compiling: $(realpath --relative-to="$BASE_DIR" "$tex_file") ... "
    
    if pdflatex -interaction=batchmode -output-directory="$dir_name" "$tex_file" > /dev/null 2>&1; then
        # Check page count via pdfinfo
        if command -v pdfinfo > /dev/null 2>&1; then
            local pages=$(pdfinfo "$pdf_file" | grep -a "Pages:" | awk '{print $2}')
            if [ "$pages" -eq 1 ]; then
                echo -e "\033[0;32m[OK - Exactly 1 Page]\033[0m"
            else
                echo -e "\033[0;31m[FAILED: $pages Pages - Must be 1 Page!]\033[0m"
                PAGE_VIOLATION_COUNT=$((PAGE_VIOLATION_COUNT + 1))
            fi
        else
            echo -e "\033[0;32m[OK (pdfinfo not found)]\033[0m"
        fi
        COMPILE_COUNT=$((COMPILE_COUNT + 1))
    else
        echo -e "\033[0;31m[COMPILATION ERROR]\033[0m"
        ERROR_COUNT=$((ERROR_COUNT + 1))
    fi
}

if [ -n "$1" ]; then
    if [ -f "$1" ]; then
        compile_file "$1"
    else
        echo "Error: File $1 does not exist."
        exit 1
    fi
else
    while IFS= read -r -d '' file; do
        compile_file "$file"
    done < <(find "$VERSIONS_DIR" -name "*.tex" -print0 | sort -z)
fi

echo "======================================================================"
echo " Compilation Summary:"
echo " Total files processed: $COMPILE_COUNT"
echo " Errors: $ERROR_COUNT"
echo " Page violations (>1 page): $PAGE_VIOLATION_COUNT"
echo "======================================================================"

if [ "$ERROR_COUNT" -gt 0 ] || [ "$PAGE_VIOLATION_COUNT" -gt 0 ]; then
    exit 1
else
    echo -e "\033[0;32mAll documents passed 1-page verification successfully!\033[0m"
fi
