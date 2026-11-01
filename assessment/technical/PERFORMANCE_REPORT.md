# PERFORMANCE_REPORT

- No new dedicated performance benchmark campaign executed in this run.
- Current-tree full tests / CI-equivalent source gate runtime observed on
  2026-08-28: 133.77s for 2110 passed and 10 expected skips on CPython
  3.13.14 x64. The skips were 3 opt-in Clumsy hardware tests, 3 redactor tests
  requiring symlink privilege, 3 opt-in hardware-smoketest tests, and
  1 installer symlink test.
- This test-gate runtime is not an application performance benchmark.
- Performance conclusions are PARTIAL and not treated as production SLA proof.
