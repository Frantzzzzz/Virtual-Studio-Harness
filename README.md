# Virtual Studio Harness

在已有 Blender 影棚中，为动作导演和摄影指导提供共同的场景事实，再将它们的计划执行为可检查、可局部返修的胶囊人预演。

当前基于真实 Forest 小样，已完成单场基线与 **5 集 × 8 分钟** 的胶囊人字幕预演：30 场、152 镜、57,600 帧，并保存五份可编辑 Blender 场景。目标是复用局部影棚构建与拍摄流程；三方自主协商和新剧情修改后的完整影响传播尚未验证。

五集生产实现位于 `season/`：分集编剧、精确状态继承、动作原语、动态构图包络、局部摄影返修、像素缓存和整集动画回读。实现、实测成本与验收边界见 [docs/season-production.md](docs/season-production.md)，不含本机路径的结果摘要见 [docs/season-results.json](docs/season-results.json)。本地 `season_report.json` 保留逐场证据，视频与 blend 不随源码上传。

## 已验证的单场执行链

```text
已有场景 + 固定剧情
        ↓
共享局部影棚：人物站位 / 路线 / 交互点 / 摄影候选
        ↓
动作导演 → 结构化动作计划 → 采样、检查、写入 Blender
        ↓                          ↓ 实际动作观察
摄影指导 → 摄影计划 → camera harness 导入与检查
        ↑                   │
        └── 具体失败帧与反馈 ──┘
                            ↓
                       复验 → 渲染
```

Forest 基线输出 **17.625 秒 / 24 FPS / 423 帧 / 7 镜**。首版摄影有 51 帧盒子遮挡，摄影指导调整两处摄影设计，保留人物与道具动画。记录见 [docs/forest-pilot.md](docs/forest-pilot.md)。

## 目录与复用边界

- `experiments/forest_capsules/`：已运行小样的动作、摄影、检查与交付代码；当前版本将本机路径和局部站位等提取到配置。
- `studio_config.py`：纯标准库配置加载、路径与坐标校验；不启动 Blender，不调用模型。
- `configs/forest.example.json`：Forest 胶囊小样配置模板。
- `docs/architecture.md`：模块来源、创作责任和接口边界。
- `tests/`：配置失败边界、关键参数迁移和源码完整性检查。

复用已有 camera harness 的场景索引、几何验证、观察、候选机位搜索和相机轨迹模块；通过外部本地 checkout 导入，不复制整份上游源码。WorldOS 也作为外部依赖，采用其动作采样和角色指导文档。

## 本地配置

需要 Python 3.10+、支持原小样 API 的 Blender（原记录为 5.1.2），以及外部 camera harness / WorldOS checkout。Python 图像依赖见 `requirements.txt`；模型工单还需要已登录的 Codex CLI。

```bash
cp configs/forest.example.json config.local.json
# 编辑本机路径与场景配置；不要提交 config.local.json
export STUDIO_CONFIG="$PWD/config.local.json"
python3 studio_config.py --check-paths
python3 -m unittest discover -s tests -v
```

模板中的占位路径必须替换。当前 pilot 还需要既有校准动画和对应的 `native_episode.json`，用于角色/桌面设定与候选视点的校准姿态；这两项没有随仓库发布。它不是从任意新 blend 开箱即用的场地发现器。

参数路径以配置文件所在目录为基准。`output_dir` 必须是独立目录，不能包含输入源文件。新实验应使用新的输出目录。

## 分阶段运行

下列命令只展示执行入口；**不要在准备好本机配置与必要输入前运行**。外部模型工单会将项目剧情、结构化场景信息及对应预演图发送到当前认证的模型服务，应按实验数据授权范围执行。

```bash
# 1. 测量局部影棚，整理可选历史观察，准备共享输入
python3 experiments/forest_capsules/blender_run.py prior
python3 experiments/forest_capsules/history.py
python3 experiments/forest_capsules/prepare_jobs.py

# 2. 动作导演规划，编译并实际烘焙
python3 experiments/forest_capsules/run_job.py action
python3 experiments/forest_capsules/compile_actions.py
python3 experiments/forest_capsules/blender_run.py bake

# 3. 摄影指导规划，编译并检查
python3 experiments/forest_capsules/prepare_camera.py
python3 experiments/forest_capsules/run_job.py camera
python3 experiments/forest_capsules/compile_camera.py
python3 experiments/forest_capsules/blender_run.py film_check
python3 experiments/forest_capsules/blender_run.py walk_check

# 4. 检查通过后再渲染；失败应先审阅证据、生成修订并重验
python3 experiments/forest_capsules/blender_run.py render
```

以上单场入口的动作姿态修订与摄影修订由宿主转交反馈后产生；单场 `deliver.py` 仍是对应五次原始工单的报告器，不是任意新实验的通用报告工具。五集入口另由 `season.produce` 调度有界摄影返修，见五集生产文档。不要通过伪造原始工单补齐输入。

## 单场基线的边界

- 影棚区域与人物站位候选由宿主提供，程序测量和筛查；尚未自动理解整片森林并根据剧情选址。
- Forest 分类使用名称规则，空间块不是逐棵树语义；走位代理排除 GroundPlants，不能作为全场景物理无碰撞保证。
- 摄影候选在有限校准姿态上搜索，实际动作与运镜需要重新检查。
- 胶囊没有手臂、腿部步态或真实抓握；`bend_rad` 只影响隐形交互挂点。
- 单场集成实验，未运行完整 WorldOS 应用或原生 camera harness finalize，未接 Seedance/Wan。
- 本次提取后，8 项配置/源码检查通过；用原始动作与摄影计划重放数值编译，动作采样、原生动作采样、持有事件、相机采样四份输出与原实验完全一致。尚未重跑整套 Blender / 模型流程。

本仓库仅保留代码与不含本机路径的实验摘要。blend、视频、图片、日志、原始工单和本机配置留在本地。上游来源见 [docs/architecture.md](docs/architecture.md)。
