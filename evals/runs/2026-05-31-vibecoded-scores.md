# Kernel vs grep — vibecoded eval scores (2026-05-31, manual interactive runs)

Scored with scripts/h2_eval.py over interactive session transcripts.
Arms: sudoku kernel=c7252d51 grep=e6b0344f ; locate kernel=f00193dd grep=1a52c66c
Caveats: manual runs (no --disallowedTools enforcement). Clean per-arm tool census —
 sudoku kernel: ToolSearch1 overview2 find9 Read11   sudoku grep: Bash1 Read24
 locate kernel: ToolSearch1 overview1 find10 Read19 Bash2(!)   locate grep: Bash1 Read16
Only off-protocol use: locate-kernel made 2 Bash calls (kernel arm should be find/overview/Read).
Both kernel arms used the correct per-repo ck server (ck-sudoku/ck-locate) — no cloud-MCP leak;
the .mcp.json routing fix worked. (Earlier "TodoWrite"/"cloud-leak" notes were glitch artifacts.)

## ======== SUDOKU ========
corpus root: test-repos/vibe-coded/sudoku
aspect concepts audited: []

========================================================================
  KERNEL  c7252d51-60c6-4751-88f1-7ede1a6d7ab7.jsonl
  COST  tool_calls=23  failed=0  dup_reads=0  fresh_tokens=70242  (in=46922 out=23320 cache_r=2186327)
  PATHS claimed=16  resolved=15  MISSING=['.well-known/jwks.json']
  RECALL Q1: 2/2 ✓
  RECALL Q2: 1/2  missed=['api/graphql/resolvers/sudoku_games.py']
  RECALL Q3: 3/4  missed=['terraform/dynamodb.tf']
  RECALL Q4: 2/3  missed=['web/src/graphql/client.ts']
  RECALL Q5: 3/3 ✓
  RECALL Q6: 1/4  missed=['terraform/lambda.tf', 'terraform/cloudfront.tf', 'terraform/s3.tf']
  GROUND Q1: 2/2 opened ✓
  GROUND Q2: 1/2 opened  not-opened=['api/graphql/resolvers/sudoku_games.py']
  GROUND Q3: 1/4 opened  not-opened=['api/data/users.py', 'api/data/ws_connections.py', 'terraform/dynamodb.tf']
  GROUND Q4: 2/3 opened  not-opened=['web/src/graphql/client.ts']
  GROUND Q5: 3/3 opened ✓
  GROUND Q6: 1/4 opened  not-opened=['terraform/lambda.tf', 'terraform/cloudfront.tf', 'terraform/s3.tf']

========================================================================
  GREP    e6b0344f-692d-4c13-aae6-973da45b6252.jsonl
  COST  tool_calls=25  failed=0  dup_reads=0  fresh_tokens=81620  (in=59347 out=22273 cache_r=1699416)
  PATHS claimed=22  resolved=21  MISSING=['.well-known/jwks.json']
  RECALL Q1: 2/2 ✓
  RECALL Q2: 2/2 ✓
  RECALL Q3: 3/4  missed=['terraform/dynamodb.tf']
  RECALL Q4: 2/3  missed=['web/src/graphql/client.ts']
  RECALL Q5: 3/3 ✓
  RECALL Q6: 1/4  missed=['terraform/lambda.tf', 'terraform/cloudfront.tf', 'terraform/s3.tf']
  GROUND Q1: 2/2 opened ✓
  GROUND Q2: 2/2 opened ✓
  GROUND Q3: 3/4 opened  not-opened=['api/data/ws_connections.py']
  GROUND Q4: 2/3 opened  not-opened=['web/src/graphql/client.ts']
  GROUND Q5: 3/3 opened ✓
  GROUND Q6: 4/4 opened ✓

========================================================================
  COMPARE
  arm      calls failed  dup fresh_tok halluc  grounded  recalled
  ---------------------------------------------------------------
  kernel      23      0    0     70242      1     10/18     12/18
  grep        25      0    0     81620      1     16/18     13/18

## ======== LOCATE_ANYTHING_SETUP ========
corpus root: test-repos/vibe-coded/locate_anything_setup
aspect concepts audited: []

========================================================================
  KERNEL  f00193dd-70cf-440d-9f77-bd7a024e7dee.jsonl
  COST  tool_calls=33  failed=0  dup_reads=4  fresh_tokens=65085  (in=32378 out=32707 cache_r=4074528)
  PATHS claimed=23  resolved=22  MISSING=['self.lock']
  RECALL Q1: 2/2 ✓
  RECALL Q2: 3/3 ✓
  RECALL Q3: 2/2 ✓
  RECALL Q4: 4/4 ✓
  RECALL Q5: 2/2 ✓
  RECALL Q6: 3/3 ✓
  GROUND Q1: 2/2 opened ✓
  GROUND Q2: 3/3 opened ✓
  GROUND Q3: 2/2 opened ✓
  GROUND Q4: 4/4 opened ✓
  GROUND Q5: 2/2 opened ✓
  GROUND Q6: 3/3 opened ✓

========================================================================
  GREP    1a52c66c-43d7-45ed-8692-2cfc1e6e66fd.jsonl
  COST  tool_calls=17  failed=0  dup_reads=0  fresh_tokens=48095  (in=28443 out=19652 cache_r=2070378)
  PATHS claimed=21  resolved=19  MISSING=['preprocessor_config.json', 'self.lock']
  RECALL Q1: 2/2 ✓
  RECALL Q2: 3/3 ✓
  RECALL Q3: 2/2 ✓
  RECALL Q4: 4/4 ✓
  RECALL Q5: 2/2 ✓
  RECALL Q6: 3/3 ✓
  GROUND Q1: 2/2 opened ✓
  GROUND Q2: 3/3 opened ✓
  GROUND Q3: 2/2 opened ✓
  GROUND Q4: 4/4 opened ✓
  GROUND Q5: 2/2 opened ✓
  GROUND Q6: 3/3 opened ✓

========================================================================
  COMPARE
  arm      calls failed  dup fresh_tok halluc  grounded  recalled
  ---------------------------------------------------------------
  kernel      33      0    4     65085      1     16/16     16/16
  grep        17      0    0     48095      2     16/16     16/16
