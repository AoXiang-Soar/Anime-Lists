# 番剧年表 · Anime Lists

1990 年至今全部日本季度番的年表，勾一勾就能看清自己看过什么。

灵感来自 [anime-sedai](https://anime-sedai.egoist.dev/)。原站点很好看，但用的是一份精选榜单，每季只有几十部热门作品，冷门番基本找不到。这里换成 AniList 的全量数据重新做了一份：37 年、148 个季度、5600 多部作品，每季独立成条，小众番、OVA、泡面番都在里面。

打开就是一张按年份和季度铺开的表。点一下封面表示「看过」，点左下角的星标表示「想补」，没勾的卡片是灰的，勾过的会亮起来——一眼就能看出自己的追番轨迹。

## 快速开始

**方式一：直接用 exe（推荐）**

下载 [`dist/AnimeLists.exe`](dist/AnimeLists.exe) 双击即可，约 10 MB，不需要装 Python 或任何运行环境。

它会把页面释放到 `%LOCALAPPDATA%\AnimeLists\<版本>`，在本机回环地址起一个只服务这个页面的微型服务，然后打开默认浏览器。你的记录会写在 **exe 同目录**的 `anime-lists-data.json`，换电脑时把 exe 和这个文件一起拷走就行。

**方式二：直接打开网页**

下载整个仓库，双击 `index.html`，不需要服务器、不需要构建。所有数据都以 `data/*.js` 的形式通过 `<script>` 注入，`file://` 下工作正常。放到 GitHub Pages / nginx 上跑也一样。

## 怎么用

- **勾选**：点卡片 = 看过，再点一次取消。右上角按钮可以整季全选 / 清空。
- **补番列表**：卡片左下角的 ★ 收藏（不影响已看状态），顶栏「★ 补番列表」单独查看，按年份分组，可批量清空或直接标记已看。
- **热力图**：37 年 × 4 季的方格，颜色越亮表示那一季看得越多，点格子直接跳年。
- **统计**：顶栏显示收录完成度和总时长，侧栏根据你的口味判断「动画世代」（OVA 黄金黎明、轻改盛世、异世界元年……）和追番段位。
- **筛选和搜索**：按类型 / 时长 / 是否肉番过滤；搜索支持中文名、日文原名、罗马字、英文名和别名。
- **海报**：一键生成 PNG，包含**全部**已看番剧（按时间降序），带年度柱状图、类型分布和一段基于番数与时长的追番评价。
- **分享**：勾选状态会编码进链接，直接发给别人就能还原你的清单。

## 记录存在哪

所有记录就是一份 JSON：`{ watched: [番剧 id…], starred: [番剧 id…] }`，另带版本号和导出时间。

| 打开方式 | 自动保存到 | 自动恢复 |
| --- | --- | --- |
| 双击 exe | exe 同目录的 `anime-lists-data.json`，每次勾选 / 取消 / 收藏即时写入 | 启动时读取同目录最新的 `anime-lists*.json` |
| 双击 `index.html` 或托管在网页上 | 点一次「选择保存文件」后静默写入你挑的那个文件 | 同一个文件（受浏览器授权限制） |

浏览器不允许网页自己新建文件，所以纯网页版第一次需要你手动选一下保存位置；exe 版没有这个限制，全自动。自动保存默认开启，可以在侧栏关掉——关掉之后状态只留在链接里。任何时候都能用「导出 JSON」另存一份快照，exe 模式下同样直接写进 exe 目录。

> 注意：`anime-lists-data.json` 是你的个人追番记录。仓库默认通过 `.gitignore` 忽略它，不会被推到 GitHub；想让它跟着仓库同步，把 `.gitignore` 里对应的那两行删掉即可（公开仓库意味着任何人都能看到你的清单）。

## 收录范围

| 维度 | 规则 |
| --- | --- |
| 时间 | 1990 - 2026 年，按 AniList 的 seasonYear 归档 |
| 地区 | 只收日漫（`countryOfOrigin = JP`），国创 / 韩番 / 欧美动画不收 |
| 类型 | TV、TV_SHORT、ONA、OVA、SPECIAL；不含剧场版和音乐 MV |
| 集数 | 只收 9 集及以上，标准 12 / 24 集季番全收，长篇年番保留（可筛选隐藏） |
| 状态 | 只收已经播完的作品，连载中和未开播的新番不列出 |
| 里番 | 排除 `Hentai` 标签 |
| 肉番 | 剧情完整、集数标准的成人向 TV 番保留（《回复术士的重启人生》《异种族风俗娘评鉴指南》《终末的后宫》等）；单集不足 20 分钟或不足 9 集的成人向 OVA / ONA 按纯卖肉排除 |

判定逻辑集中在 `scripts/build_data.py` 的几个常量里（`MIN_EPISODES`、`AIRING_STATUSES`、`ADULT_KEEP`、`is_hentai()`），想改口径直接改那里再重建；前端的在线更新用的是同一套规则，见 `app.js` 的 `eligibleOnline()`。

已知的不足：

- 1990 年代的 OVA 库存在 AniList 上本身就不完整，越早越明显。TV 番是完整的（用 startDate 精确翻页逐条核对过 2010 / 2019 年，日本 TV 番零遗漏）。
- 中文名来自 bangumi-data，覆盖率约六成，其余显示日文原名；近年作品覆盖率高，早期偏低。
- 12 月开播的跨年番按 AniList 的季度归属（通常是次年冬季），不会重复计入。
- 在线更新只刷新最近几个季度（数据生成时间往前 45 天以内，最多 8 个），更早年份的变动需要重新跑构建脚本。

## 数据是怎么来的

抓取和构建是两个脚本，原始结果会缓存在 `data/raw/`，可以随时重跑：

```bash
python scripts/fetch_anilist.py      # 抓 AniList，增量，已抓过的年份自动跳过（整轮约 10 分钟）
python scripts/build_data.py         # 合并中文名，生成站点用的 data/*.js
python scripts/build_exe.py          # 重新打包 dist/AnimeLists.exe
```

站点数据本身就是 `window.ANIME_DATA[2021] = [...]` 这样的 JS 赋值，去掉这层包装就是纯 JSON；Python 侧读取见 `scripts/anime_data.py`。每条形如：

```json
{
  "id": 113425,
  "t": { "zh": "回复术士的重来人生", "zhAlt": ["棍勇"], "romaji": "Kaifuku Jutsushi no Yarinaoshi",
         "en": "Redo of Healer", "native": "回復術士のやり直し" },
  "f": "TV", "ep": 12, "du": 24,
  "y": 2021, "s": "WINTER",
  "d": "2021-01-13", "e": "2021-03-31",
  "g": ["Action", "Adventure", "Ecchi", "Fantasy"],
  "k": ["ecchi", "adult"],
  "sc": 63, "po": 169000, "fa": 22000,
  "cov": "https://s4.anilist.co/…", "col": "#e5a45c",
  "stu": "TNK", "src": "Light Novel", "mal": 40750, "bgm": 295017
}
```

分享链接里的 `w` / `s` 参数是 `data/catalog.js` 中 `ids` 顺序的位图，编解码见 `app.js` 的 `readHash` 和 `b64url`。

## 目录结构

```
index.html              页面
styles.css              样式
app.js                  全部前端逻辑（原生 JS，无依赖、无构建步骤）
data/index.js           年份清单与每年每季数量
data/catalog.js         固定顺序的全量索引（位图、统计、搜索都用它）
data/search.js          搜索索引（懒加载）
data/<year>.js          每年的条目，按需注入
data/raw/               原始抓取缓存（重新生成数据时才需要，体积约 16 MB）
scripts/                抓取、构建、打包、自测脚本
packaging/launcher.py   exe 启动器
dist/AnimeLists.exe     打包产物
```

## 自测

自测脚本用无头 Chrome 走真实交互，不依赖任何测试框架：

```bash
python scripts/smoke_test.py            # 默认用 file:// 打开页面跑全流程
python scripts/check_titles.py          # 抽查知名番是否在库
python scripts/test_update.py           # 强制跑一遍在线更新（需要联网）
python scripts/test_save_server.py      # exe 内置服务：静态资源、存档端点、路径穿越防护
python scripts/test_autosave.py         # 自动保存与自动恢复
python scripts/test_autosave.py --exe   # 同上，跑打包好的 exe
python scripts/test_exe.py              # 用 exe 的地址跑完整交互测试
```

## 许可

代码以仓库中的 MIT 许可证发布。但有两点需要说明：

- 番剧数据来自 [AniList](https://anilist.co) GraphQL API，遵循 **CC BY-NC-SA 4.0**：署名、非商业使用、相同方式共享。`data/` 目录下的数据文件是 AniList 数据的衍生作品，同样受这个许可约束，不能单独按 MIT 使用。
- 中文标题来自 [bangumi-data](https://github.com/bangumi-data/bangumi-data)（MIT）。封面图直接引用 AniList CDN，版权归各自权利人所有。

个人自用、分享清单都没有问题；如果要拿它做商业用途，需要先确认 AniList 数据的授权范围。

## 致谢

- 交互灵感：[anime-sedai](https://anime-sedai.egoist.dev/)
- 数据：[AniList](https://anilist.co)、[bangumi-data](https://github.com/bangumi-data/bangumi-data)
