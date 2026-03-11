#!/bin/bash

# Test Runner Script for Configuration Service
# Runs all tests and generates comprehensive reports

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$TEST_DIR/../.." && pwd)"
REPORT_DIR="$TEST_DIR/reports"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Create report directory
mkdir -p "$REPORT_DIR"

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Configuration Service - Test Runner                      ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Function to print section header
print_header() {
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

# Function to print result
print_result() {
    if [ $1 -eq 0 ]; then
        echo -e "${GREEN}✅ $2${NC}"
    else
        echo -e "${RED}❌ $2${NC}"
        exit 1
    fi
}

# 1. Check dependencies
print_header "1. Checking Dependencies"
echo "Checking pytest..."
python -m pytest --version
print_result $? "pytest installed"

echo "Checking pytest-asyncio..."
python -c "import pytest_asyncio; print(f'pytest-asyncio {pytest_asyncio.__version__}')"
print_result $? "pytest-asyncio installed"

echo "Checking pytest-cov..."
python -c "import pytest_cov; print('pytest-cov installed')"
print_result $? "pytest-cov installed"

# 2. Run DAO tests
print_header "2. Running DAO Layer Tests"
echo "Running test_chat_agent_config_dao.py..."
python -m pytest "$TEST_DIR/test_chat_agent_config_dao.py" -v --tb=short \
    --json-report --json-report-file="$REPORT_DIR/dao_tests_${TIMESTAMP}.json" \
    > "$REPORT_DIR/dao_tests_${TIMESTAMP}.log" 2>&1
print_result $? "DAO tests completed"

echo "Running test_chat_agent_config_dao_extended.py..."
python -m pytest "$TEST_DIR/test_chat_agent_config_dao_extended.py" -v --tb=short \
    --json-report --json-report-file="$REPORT_DIR/dao_extended_tests_${TIMESTAMP}.json" \
    > "$REPORT_DIR/dao_extended_tests_${TIMESTAMP}.log" 2>&1
print_result $? "DAO extended tests completed"

# 3. Run Service tests
print_header "3. Running Service Layer Tests"
echo "Running test_chat_agent_config_service.py..."
python -m pytest "$TEST_DIR/test_chat_agent_config_service.py" -v --tb=short \
    --json-report --json-report-file="$REPORT_DIR/service_tests_${TIMESTAMP}.json" \
    > "$REPORT_DIR/service_tests_${TIMESTAMP}.log" 2>&1
print_result $? "Service tests completed"

# 4. Run Router tests
print_header "4. Running Router Layer Tests"
echo "Running test_chat_agent_config_router.py..."
python -m pytest "$TEST_DIR/test_chat_agent_config_router.py" -v --tb=short \
    --json-report --json-report-file="$REPORT_DIR/router_tests_${TIMESTAMP}.json" \
    > "$REPORT_DIR/router_tests_${TIMESTAMP}.log" 2>&1
print_result $? "Router tests completed"

# 5. Run Integration tests
print_header "5. Running Integration Tests"
echo "Running test_chat_agent_config_integration.py..."
python -m pytest "$TEST_DIR/test_chat_agent_config_integration.py" -v --tb=short \
    --json-report --json-report-file="$REPORT_DIR/integration_tests_${TIMESTAMP}.json" \
    > "$REPORT_DIR/integration_tests_${TIMESTAMP}.log" 2>&1
print_result $? "Integration tests completed"

# 6. Run all tests with coverage
print_header "6. Running All Tests with Coverage"
echo "Running all tests with coverage report..."
python -m pytest "$TEST_DIR" -v \
    --cov=configuration \
    --cov-report=html:"$REPORT_DIR/coverage_html_${TIMESTAMP}" \
    --cov-report=json:"$REPORT_DIR/coverage_${TIMESTAMP}.json" \
    --cov-report=term-missing \
    --json-report --json-report-file="$REPORT_DIR/all_tests_${TIMESTAMP}.json" \
    > "$REPORT_DIR/all_tests_${TIMESTAMP}.log" 2>&1
print_result $? "All tests with coverage completed"

# 7. Generate summary report
print_header "7. Generating Summary Report"

SUMMARY_FILE="$REPORT_DIR/TEST_SUMMARY_${TIMESTAMP}.md"

cat > "$SUMMARY_FILE" << 'EOF'
# Test Execution Summary

## Execution Details

EOF

echo "**Timestamp**: $TIMESTAMP" >> "$SUMMARY_FILE"
echo "**Test Directory**: $TEST_DIR" >> "$SUMMARY_FILE"
echo "" >> "$SUMMARY_FILE"

# Count tests
echo "## Test Results" >> "$SUMMARY_FILE"
echo "" >> "$SUMMARY_FILE"

DAO_COUNT=$(grep -c "PASSED\|FAILED" "$REPORT_DIR/dao_tests_${TIMESTAMP}.log" || echo "0")
DAO_EXT_COUNT=$(grep -c "PASSED\|FAILED" "$REPORT_DIR/dao_extended_tests_${TIMESTAMP}.log" || echo "0")
SERVICE_COUNT=$(grep -c "PASSED\|FAILED" "$REPORT_DIR/service_tests_${TIMESTAMP}.log" || echo "0")
ROUTER_COUNT=$(grep -c "PASSED\|FAILED" "$REPORT_DIR/router_tests_${TIMESTAMP}.log" || echo "0")
INTEGRATION_COUNT=$(grep -c "PASSED\|FAILED" "$REPORT_DIR/integration_tests_${TIMESTAMP}.log" || echo "0")

echo "| Layer | Tests | Status |" >> "$SUMMARY_FILE"
echo "|-------|-------|--------|" >> "$SUMMARY_FILE"
echo "| DAO | $DAO_COUNT | ✅ |" >> "$SUMMARY_FILE"
echo "| DAO Extended | $DAO_EXT_COUNT | ✅ |" >> "$SUMMARY_FILE"
echo "| Service | $SERVICE_COUNT | ✅ |" >> "$SUMMARY_FILE"
echo "| Router | $ROUTER_COUNT | ✅ |" >> "$SUMMARY_FILE"
echo "| Integration | $INTEGRATION_COUNT | ✅ |" >> "$SUMMARY_FILE"
echo "" >> "$SUMMARY_FILE"

TOTAL=$((DAO_COUNT + DAO_EXT_COUNT + SERVICE_COUNT + ROUTER_COUNT + INTEGRATION_COUNT))
echo "**Total Tests**: $TOTAL" >> "$SUMMARY_FILE"
echo "" >> "$SUMMARY_FILE"

echo "## Coverage Report" >> "$SUMMARY_FILE"
echo "" >> "$SUMMARY_FILE"
echo "Coverage reports generated:" >> "$SUMMARY_FILE"
echo "- HTML Report: \`coverage_html_${TIMESTAMP}/index.html\`" >> "$SUMMARY_FILE"
echo "- JSON Report: \`coverage_${TIMESTAMP}.json\`" >> "$SUMMARY_FILE"
echo "" >> "$SUMMARY_FILE"

echo "## Test Logs" >> "$SUMMARY_FILE"
echo "" >> "$SUMMARY_FILE"
echo "Individual test logs:" >> "$SUMMARY_FILE"
echo "- DAO Tests: \`dao_tests_${TIMESTAMP}.log\`" >> "$SUMMARY_FILE"
echo "- DAO Extended Tests: \`dao_extended_tests_${TIMESTAMP}.log\`" >> "$SUMMARY_FILE"
echo "- Service Tests: \`service_tests_${TIMESTAMP}.log\`" >> "$SUMMARY_FILE"
echo "- Router Tests: \`router_tests_${TIMESTAMP}.log\`" >> "$SUMMARY_FILE"
echo "- Integration Tests: \`integration_tests_${TIMESTAMP}.log\`" >> "$SUMMARY_FILE"
echo "- All Tests: \`all_tests_${TIMESTAMP}.log\`" >> "$SUMMARY_FILE"
echo "" >> "$SUMMARY_FILE"

print_result $? "Summary report generated"

# 8. Print final summary
print_header "8. Test Execution Complete"
echo ""
echo -e "${GREEN}✅ All tests executed successfully!${NC}"
echo ""
echo "Reports saved to: $REPORT_DIR"
echo ""
echo "Key files:"
echo "  - Summary: $SUMMARY_FILE"
echo "  - Coverage HTML: $REPORT_DIR/coverage_html_${TIMESTAMP}/index.html"
echo "  - All Tests Log: $REPORT_DIR/all_tests_${TIMESTAMP}.log"
echo ""
echo -e "${BLUE}To view coverage report:${NC}"
echo "  open $REPORT_DIR/coverage_html_${TIMESTAMP}/index.html"
echo ""
echo -e "${BLUE}To view test summary:${NC}"
echo "  cat $SUMMARY_FILE"
echo ""
