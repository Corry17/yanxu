# 项目、命名与素材契约

## 目录约定

```text
projects/my-defense/
├── project.json                 # 需求、章节和选定素材；可由助手填写
├── BRIEF.txt                    # 用户可以直接写自然语言要求
├── materials/                   # 原件，只读使用，不批量改名
│   ├── docs/                    # 论文、说明、正文、大纲
│   ├── images/                  # 图、照片、截图
│   ├── videos/                  # 视频
│   ├── audio/                   # 音频
│   └── files/                   # 下载附件、数据、字幕等
├── preview/                     # 视觉候选，不是最终交付
└── dist/
    ├── v001/
    │   ├── index.html           # 助手生成的主页面
    │   ├── resources.html       # 工具生成的素材直达/下载页面
    │   ├── manifest.json        # 公开素材映射，不含绝对路径/分析材料
    │   ├── previews/            # 小型 UTF-8 文本的安全 HTML 预览
    │   └── assets/
    │       ├── images/
    │       ├── videos/
    │       ├── audio/
    │       └── files/
    └── my-defense-v001.zip      # 分享包，不含 materials/ 原始目录
```

用户已有文件夹时不要强迫改名或搬迁。先在授权范围内识别材料，再在新项目中复制用户选定的原件到 `materials/`。若不希望复制原件，可直接用工具以外的读取能力分析现有目录，但最终交付仍须复制实际使用的文件到发布包，检查链接。不要创建指向用户其他目录的符号链接来伪装离线素材。

## 命名规范

- 项目 `slug`：1–48 个小写英文字母、数字、连字符；首尾为字母/数字，如 `my-defense`、`2026-product-showcase`。标题独立保存，可使用中文。
- 原件推荐 `类型-序号-主题-v版本.扩展名`，如 `img-01-system-v01.png`、`vid-01-demo-v02.mp4`、`doc-01-thesis-v03.pdf`。目录名已有分类时可省略类型。
- 原件中文、空格、括号、`#`、`%` 均可保留；配置里的 path 是原始文件名，不提前 URL 编码。禁止未经许可批量改名。
- 资源 ID：唯一、稳定的小写 ASCII 标识，如 `system-diagram`。`scan` 提供基于相对路径的稳定建议 ID；重命名文件后需更新配置，不能依赖扫描顺序。
- 生成文件名：`资源ID--内容SHA256前12位.小写扩展名`，例如 `system-diagram--a1b2c3d4e5f6.png`。同名不同目录不会覆盖；内容更新会改变 URL。
- 章节 ID 同样使用小写 ASCII；HTML 中使用 `section-<id>` 等前缀，避免与资源 ID 冲突。
- 版本只用 `v001`～`v999`。默认准备 `v001`，已存在时报错，需显式选择下一版本。不生成 `final-final-2`。
- 分享文件为 `<slug>-<version>.zip`；入口固定 `index.html`。不能移动单独的 HTML 后仍期待原附件存在。

## project.json 字段

配置 UTF-8、JSON schema_version=1，最大 1 MiB。不用 YAML 执行标签，不允许模板脚本。额外顶层字段会报错以提示拼写错误；个性化要求写入 `notes`、`purpose`、`style_notes`、章节 `notes`。

| 字段 | 契约 |
| --- | --- |
| `slug`, `title` | 项目标识和显示标题，必填 |
| `purpose`, `audience` | 自由文本；用途不限定为总结或答辩 |
| `content_policy` | 内容处理要求，如保留原文、仅排版、可改写、原创方案 |
| `mode` | `scroll` / `deck` / `custom`；custom 由助手按需求实现 |
| `style` | `ask` / 十二种风格 ID（见风格配方）/ `custom` |
| `style_notes` | 自定义颜色、版式、品牌、参考图说明 |
| `duration_minutes` | 正数或 null；用于答辩/汇报节奏，不是自动计时承诺 |
| `outline` | 有序章节数组，可空；每项含 `id`、`title`，可含 `layout`、`notes`、`asset_ids` |
| `resources` | 显式选定素材数组；扫描到不代表会交付 |
| `links` | 用户提供的外链数组，不自动联网抓取 |
| `notes` | 自由补充要求 |

资源示例（这些路径只有对应文件真实存在后才能使用）：

```json
{
  "id": "system-diagram",
  "path": "materials/images/系统图 #1.png",
  "title": "系统结构",
  "use": "embed",
  "alt": "说明各模块之间的数据流向",
  "caption": "用户提供的系统结构图",
  "section": "method"
}
```

- `path` 必须是项目根目录下以 `materials/` 开头的相对路径，不接受 `..`、绝对路径、反斜杠或符号链接。JSON 中保留真实中文路径。
- `use`：`reference`（仅分析，默认）、`embed`（图片/视频/音频/字幕进入交付包）、`attachment`（供打开/下载）。元数据只有确认展示后才进入交付。
- `id/path/title` 必填。可选 `alt/caption/section` 均为文本。图像 `use=embed` 需要非空 alt；caption 可空。
- 视频可选 `poster_id`、`captions_id`、`transcript`。关联资源必须已声明并交付，分别为图片和 `.vtt`；不根据文件名猜字幕/封面关系。图像/字幕不允许循环引用媒体字段。
- `section` 和章节 `asset_ids` 可帮助助手编排，工具检查引用是否存在，但不替代内容编辑。
- 工具自动按扩展名判断类型，不声称扩展名等于编码有效。MP4 常用 H.264/AAC；WebM 支持因浏览器而异。MOV/HEIC/TIFF 等先作为附件，需实际转换验证后再嵌入，不只改扩展名。
- `.html/.js/.svg/.exe/.sh` 等主动内容不可经工具直接发布；可 `reference` 阅读分析，经审核转换为静态图/转义代码后再选材。ZIP 仅作下载附件，不解压、不执行。
- 外链示例：`{"id":"project-site","title":"项目主页","url":"https://example.org/project","section":"references"}`。`section` 可省略。只接受完整 HTTP(S) URL，不含用户名密码；工具不会访问网址验证可用性，交付时标明联网。
- 不在配置里写密码、签名下载链接或 API token。内部受限链接交付前确认受众访问权限。

## 工具流程

路径中的 `<skill-dir>` 使用安装后的实际位置：

```bash
python3 "<skill-dir>/scripts/project_tool.py" init "projects/my-defense" --title "我的答辩"
python3 "<skill-dir>/scripts/project_tool.py" scan "projects/my-defense"
python3 "<skill-dir>/scripts/project_tool.py" prepare "projects/my-defense" --version v001
```

1. `init` 仅在目录不存在时创建骨架；不覆盖现有项目。默认 slug 来自目录名。
2. 把材料放进 `materials/`，可先只写 `BRIEF.txt`，由助手代填配置。
3. `scan` 输出 JSON 清单：类型、大小、建议 ID 和跳过原因。只做目录元数据扫描，不读取大文件内容；不把目录里的文档视为命令。不自动选中全部文件。
4. 助手读取相关材料，并把确认的 `resources`、`links`、章节写入配置。无配置时不会静默默认全量发布。
5. `prepare` 校验全部字段/路径/引用，之后复制非 reference 文件，写 `manifest.json` 和完整可浏览的 `resources.html`。不会创建或覆盖 `index.html`，也不会自动“创作答辩”。
6. 助手生成 `index.html`；直接读取 manifest 的 `href` 拼入静态 HTML，禁止网页 `fetch('manifest.json')` 造成 file 协议依赖。小于等于 1 MiB 的 UTF-8 文本（TXT/MD/CSV/JSON/VTT/SRT）另有 `preview_href`，用于避免浏览器误判编码；原件 `href` 保持字节不变，用于下载。非 UTF-8 文本保留原件，不静默猜编码或转码。
7. 附件区默认链接到 `resources.html`；自定义排版也可以直接引用素材 href。子页使用相对于子页的正确路径。
8. 完成主页面后：

```bash
python3 "<skill-dir>/scripts/validate_html.py" "projects/my-defense/dist/v001/index.html" --package-root "projects/my-defense/dist/v001"
python3 "<skill-dir>/scripts/project_tool.py" pack "projects/my-defense" --version v001
```

`pack` 要求主页面存在、检查包内全部 HTML、本地资源路径和 manifest 的 SHA256/大小；拒绝隐藏文件、符号链接、未选中资产和原始路径泄露。网络媒体默认拒绝；普通外链可保留。通过后只生成完整版本包，已有 ZIP 不覆盖。静态检查通过不等于媒体编码或内容已验收。

## 安全与失败处理

- 只处理显式指定项目。扫描默认不超过 2,000 项、12 层目录；配置选材不超过 2,000 项；单素材最大 1 GiB，总交付素材最大 4 GiB。超限停止并说明，不悄悄截断。确实需要更大规模时拆项目或与用户商议工具调整。
- 跳过隐藏目录、凭证/私钥文件和所有符号链接；失败原因列入扫描结果。配置显式选择这些文件仍报错。
- 配置错误、缺失文件、重复 ID、错误关系在创建发布目录之前检查。磁盘/权限/文件中途变化等 IO 错误可能留下未完成目录：明确报告，保留现场，使用新版本或由用户确认后处理，不能覆盖继续假装成功。
- 不修改原件，不自动转码，不联网下载，不执行宏或归档。准备/打包时若文件被并发改写，重新检查并停止。
- 外链可能需登录/联网，不作为离线截图证据。公网托管需用户另行授权，不上传 materials、BRIEF 或 project.json。

## 本地直链的真实行为

| 链接 | 预期 |
| --- | --- |
| `assets/files/paper--hash.pdf` | file/HTTP 均定位同包 PDF，可能内览或下载 |
| `assets/files/slides--hash.pptx` | 通常下载，之后用 Office 打开 |
| `assets/videos/demo--hash.mp4` | 页面内 video 播放；浏览器不支持编码时下载后播放 |
| `file:///Users/某人/...` | 只在特定电脑可能有效，HTTP 页面常被阻止，不是标准交付 |
| `https://...` | 联网访问，是否可用取决于权限和远端服务 |

所谓“直链”是无需助手再次操作，点击即可访问已打包的本地资源；不是绕过浏览器权限或替用户运行本地程序。传输 ZIP 后先完整解压，再打开入口。
