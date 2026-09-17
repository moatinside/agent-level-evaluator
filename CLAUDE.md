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
2. Evaluate two separate tracks; do not collapse them into one score:
   - Execution autonomy: fixed workflow, routing, self-correction, autonomous search, process improvement
   - Collaborative/expansive learning: intent reception, judgment externalization, joint integration, critique, question expansion, practice generalization
3. Record causal order: `Evidence → Agent update → user judgment` or `user judgment → Agent structuring`
4. Treat 51-point business judgment as a jointly formed gate, not an autonomous-goal score
5. Read `docs/current-evaluation-architecture.md` and `contracts/level-contracts.yaml` — identify current evidence gates
6. Run `python3 scripts/evaluate_current_state.py` — report evidence and migration blockers
7. Treat legacy Phase files under `archive/legacy-phase/` as historical development records only
8. Never infer Agent Level promotion from legacy Phase completion

## Report Format

```markdown
## Agent Level Evaluation Report

**エージェント:** Claude Code
**評価日時:** YYYY-MM-DD

### 評価トラック
- 実行自律性: Level X相当（Evidence: ...）
- 協働・拡張学習: [観測された段階]
- 因果順序: [Evidence → Agent update → user judgment / user judgment → Agent structuring / not_observable]
- 51点ゲート: [状態]

### 単一Levelの扱い
Evidence Gate、人間承認、連続した実運用証拠なしに総合Levelを断定しない。

### 次のステップ
1. ...
```

## Tips

- This is a self-assessment. Be honest — the goal is improvement, not a high score.
- For each axis, consider your actual capabilities demonstrated in past conversations.
- If unsure, run `python3 scripts/evaluate.py --quick` for a baseline estimate.
