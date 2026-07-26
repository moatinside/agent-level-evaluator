# Agent Level Evaluator — Claude Code Instructions

Read `AGENTS.md` first — this repo is an agent self-evaluation framework.

## Quick Start

```bash
# Clone and evaluate yourself
git clone https://github.com/moatinside/agent-level-evaluator.git
cd agent-level-evaluator
```

Then ask the user: "自己評価を開始しますか？"

## Evaluation Protocol

Follow the procedure in `AGENTS.md` Step-by-Step:

1. Read `FRAMEWORK.md` — understand Level 1-9
2. Self-evaluate on 6 axes (0-100 each):
   - Ensemble reasoning (Level 4)
   - Self-validation (Level 5)
   - Agentic Search (Level 6)
   - Self-evolution (Level 7)
   - Dynamic routing (Level 3)
   - Workflow execution (Level 2)
3. Determine overall level
4. Read `CHECKPOINTS.md` — identify next milestones
5. Output evaluation report

## Report Format

```markdown
## Agent Level Evaluation Report

**エージェント:** Claude Code
**評価日時:** YYYY-MM-DD

### スコア
- アンサンブル推論: XX/100
- 自己修正ループ: XX/100
- Agentic Search: XX/100
- 自己進化: XX/100
- 動的ルーティング: XX/100
- ワークフロー実行: XX/100

### 総合レベル: Level X

### 次のステップ
1. ...
```

## Tips

- This is a self-assessment. Be honest — the goal is improvement, not a high score.
- For each axis, consider your actual capabilities demonstrated in past conversations.
- If unsure, run `python3 scripts/evaluate.py --quick` for a baseline estimate.
