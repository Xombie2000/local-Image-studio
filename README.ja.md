# Local Image Studio

[English](README.md) | [日本語](README.ja.md)

Local Image Studioは、MFLUXを使ってローカルで画像を生成するmacOS向けの実験的アプリです。FLUX.2 KleinとKrea 2 Turboによる画像生成、SeedVR2によるアップスケール、画像ライブラリ、プロジェクト管理をネイティブSwiftUIで提供します。

オプションのプロンプト改善機能は、LM Studio（`127.0.0.1:1234`）とoMLX（`127.0.0.1:8000`）の両方からローカルチャットモデルを検出します。起動中の各サーバーのモデルは`LMS —`または`oMLX —`という接頭辞付きで同じ選択メニューに表示され、改善リクエストは選択したモデルのサーバーへ送信されます。

このリポジトリは現在、**Apple Silicon向け開発者プレビュー**です。Developer IDによる署名や公証を済ませた一般ユーザー向けリリースではありません。MacにMFLUXランタイムとモデルがすでに用意されていることを前提とし、アプリからモデルを自動ダウンロードすることはありません。

アプリは日本語と英語に対応しています。macOSでアプリに設定された言語を使用し、対応する翻訳がない場合は英語を表示します。

## 動作要件

- macOS 13以降を搭載したApple Silicon Mac
- Python 3.10以降
- `~/.local/share/uv/tools/mflux/bin/python`にあるMFLUX 0.19.1およびMLX 0.32.2
- 使用するモデルのローカルキャッシュ

MFLUXのPython実行ファイルが別の場所にある場合は、起動前に`LIS_MFLUX_PYTHON`を設定してください。

## ビルドとインストール

リポジトリのルートで次を実行します。

```sh
./build_v2_app.sh
```

スクリプトはarm64アプリをコンパイルし、アイコンを作成してアドホック署名を適用した後、`~/Applications/Local Image Studio.app`にインストールします。既存のアプリを初めて置き換える際は、`~/Applications/Local Image Studio v1.app`として保存します。

`~/Applications`を変更せずにビルドを確認するには、`./build_v2_app.sh --build-only`を実行してください。アプリは`build/Local Image Studio.app`に作成されます。

このプレビューはDeveloper ID署名およびAppleの公証を受けていないため、初回起動時に「システム設定」で許可が必要になる場合があります。

## テスト

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
./tests/run_swift_state_tests.sh
```

推論およびテレメトリ用スクリプトには、設定済みのMFLUX環境とモデルキャッシュが必要です。通常のユニットテストは偽のワーカーを使い、モデルをダウンロードしません。

## データとプライバシー

- バックエンドは`127.0.0.1`のみにバインドし、起動ごとに生成するランダムトークンで認証します。
- 推論ワーカーではHugging FaceとTransformersのオフラインモードを有効にします。
- 生成画像は`~/Pictures/Local Image Studio/`に保存します。
- メタデータは`~/Library/Application Support/Local Image Studio/history.sqlite3`に保存します。
- LoRAは`~/Library/Application Support/Local Image Studio/LoRAs/`に追加できます。

使用中のプロジェクトは`.lisproject`パッケージです。アーカイブ時は可逆圧縮WebPをZIPコンテナに保存し、復元時は記録済みのパスにPNGを再作成します。

## 現在のリリース状態

`v2.0.0-preview.1`のようなプレリリース版として公開することを想定しています。現在はarm64専用で、ローカルのアドホック署名のみです。一般公開版ではDeveloper ID署名とAppleの公証も必要です。

## ライセンス

Local Image Studioは[MIT License](LICENSE)で公開します。MFLUX由来の互換性ファイルには、[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)に記載した上流のMITライセンス表示が引き続き適用されます。このリポジトリではモデルの重みを配布していません。各モデルの重みには、それぞれのライセンスおよび利用条件が適用されます。
