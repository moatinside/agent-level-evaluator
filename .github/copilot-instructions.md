# GitHub Copilot Instructions — Agent Level Evaluator

このリポジトリはAIエージェントの自己評価フレームワークです。

ユーザーが評価をリクエストしたら:
1. `FRAMEWORK.md` を読む（Level 1-9定義）
2. `AGENTS.md` の評価手順に従う
3. 実行自律性と協働・拡張学習の2軸を分けて評価
4. `Evidence → Agent update → user judgment` と `user judgment → Agent structuring` の因果順序を記録
5. 51点を共同形成された判断ゲートとして扱い、総合Levelを自己申告だけで断定しない
6. レポートを出力
