# 可裁剪命令驱动运行时：最终内核设计框架 v1.0

**设计日期：2026-09-05**  
**适用项目：LaserCNCv3.0 及后续不需要 Project/Document 的 C++ 应用**  
**文档状态：目标架构与实施契约，不代表代码已经实现、测试通过或 Kernel 已 Frozen。**

> 一套公共命令与任务执行核心；按需装配自动化、持久执行、工作区和外部控制。命令管理业务边界，算法内部保持直接 C++ 调用。顺序脚本与原子组使用同一套计划表达，但使用不同的提交语义。

---

## 0. 决策、依据与适用范围

### 0.1 最终决策

采用 **模块化单体 + 静态 Library 模块 + 显式 Host 装配 + Ports/Adapters**。以 Windows x64、C++20 为首个正式支持组合。Core 不依赖 Qt、OCCT、CAD/CAM、控制卡 SDK、Document、SQL 实现或 AI 模型。

“可裁剪”是独立组件按需构建、链接、安装和启动，不是运行期热卸载。第三方依赖自身可以继续按其要求以 DLL 交付；静态模块不等于产品必须是单个静态 EXE。

新内核是应用的**控制与执行层**，不是实时伺服内核，也不是要求每个小程序采用的万能框架。对于需要命令调用、长任务、交互控制、日志和自动化的应用，提供统一开箱即用组合。

### 0.2 本轮收敛的关键点

| 决策 | 明确规则 |
|---|---|
| Project/Document | 从必选核心上移到 DocumentWorkspace，不删除其能力 |
| 通用执行 | Command、Query、Task、取消、资源、授权原语、观测与生命周期属于 CoreRuntime |
| 自动化 | 沿用一套 Script/Plan AST 与编译/解释机制，不另造重复的 Plan 引擎 |
| 原子组 | 由状态扩展提供；首版仅同一文档的短、有界、无外部副作用操作 |
| 顺序批执行 | 可以逐步进入普通命令入口；减少往返，但不假装只提交一次 |
| 业务算法 | 在受治理的业务边界内部直接类型化调用，不逐函数发命令 |
| 新工程 | Phase 3 作结构起点，当前 main 作实现、修复和测试来源 |
| 性能 | 同进程直调、冻结绑定、有限抽象；不通过删授权、删校验、降低耐久性换速度 |
| 对外控制 | 常驻 Host + 本地 IPC + 独立 CLI；MCP/模型工具调用是可选适配器 |
| AI 资料 | 注册契约与文档元数据作为统一来源，按需发现；资料不是授权机制 |
| 兼容 | 允许新 C++ API，不承诺跨工具链 ABI；旧数据明确读取/迁移/拒绝，禁止静默删库 |

### 0.3 版本依据

本次远端 main 核对仍为 `432434f9c43d3f83c124ac1cf23fec39018f394f`。[R1]

推荐结构起点：`52b099a9e9cabfafe5a6c2c3e95f92c2e857ed03`，Phase 3 基础设施适配器检查点。该阶段已有 Foundation、应用组合、日志、JSON、TOML、线程池与 SQLite 后端；尚未建设文档事务、TaskRuntime、Workflow 和领域 PersistenceService。[R2]

当前 main 是**修复和测试来源**，不是要全量 merge 回新核心的目标。后续的线程池排空/析构契约、持久化 Host 独占等必须承接，不能因回到早期骨架而回退。[R3,R4]

现有 Script 已具备 Command/Query/Workflow/Wait、Assign/Assert/If/ForEach/Include 及结果绑定；现有普通文档写命令分别 begin/commit，一个 handler 内则已经能够修改多个对象。顺序计划不是从零开始，通用共享事务组尚需建立新契约。[R5–R7]

本设计未重新运行目标 Windows/MSVC 的构建、CTest、ASan 或基准。历史测试记录仅是对应提交的证据，不代表新结构已经通过。本文件取代前述讨论中冲突的目标结构；旧评估文档继续作为审计背景，其原工作量预算不自动覆盖新增命令语义资料、临时计划与原子组范围。

---

## 1. 系统边界与责任分离

### 1.1 三个不同的层面

- **执行机制**：操作如何发现、校验、授权、调度、取消、观察和记录。
- **应用状态机制**：状态如何形成一致性快照、修改、撤销、提交、保存和恢复。
- **业务语义**：什么是工件、刀路、机床、工程包、加工发布，以及什么时候允许执行某项业务。

第一项属于 Core；第二项由可选 Workspace 或其他状态组件承担；第三项属于业务模块。共享状态机制不是每个业务模块各自再造一套。

### 1.2 控制数据与大数据

命令携带参数、对象身份、版本、预算和结果引用。几何、网格、刀路、仿真数据、模型文件等大数据通过有权限和寿命约束的 DataRef/AssetRef 访问，不在每一步转换为 JSON。

算法内部可以使用私有高效数据结构和第三方类型。公开命令、核心 SDK、持久身份与跨模块端口不泄漏这些类型。

本框架不承诺 1 kHz/硬实时控制。轨迹生成、设备操作和安全许可由业务与设备层处理；实时急停和硬件联锁不能依靠普通任务队列或 AI 回应。

---

## 2. 组件架构与依赖

### 2.1 逻辑结构

```text
GUI / CLI / 外部脚本 / AI Adapter
                  │
       同进程直接调用或本地 IPC
                  │
       同一受治理 ExecutionGateway
                  │
          CoreRuntime / Contracts
                  │
      注册期装配的可信执行绑定
       ┌──────────┼───────────┐
       ▼          ▼           ▼
  业务服务     Automation   状态/副作用绑定
  直接算法      Script       Workspace / 其他
       │          │           │
       └──── Task/Workflow ───┘
                  │
      可选 DurableExecution / 存储端口
                  │
             具体 Adapters
```

这是调用关系，不是反向头文件依赖许可。Core 调用的是自己声明的窄端口；具体扩展依赖 Core 的公开契约，由 Host 注入。Core 不包含扩展实现头。

### 2.2 建议构建组件

| 组件 | 主要职责 | 禁止强制依赖 |
|---|---|---|
| `Foundation` | StrongId、Value、Result/Error、Version、Schema 基础类型 | 任意运行时、数据库、GUI、领域 |
| `Contracts` | 通用请求/响应、身份、目标/资源标识、命令描述、执行与存储窄端口 | Document、RevisionSet、TransactionCommit、SQL/三方类型 |
| `CoreRuntime` | Registry、执行绑定、Command/Query、Task/Scheduler、Resource、活动租约、授权原语、事件和本地观测、Host 生命周期 | Workspace、脚本语言、SQLite、IPC、AI |
| `Automation` | 一套 Script/Plan 数据模型、表达式、编译/预算检查、顺序控制、结果绑定、原子组扩展调用 | Workspace、可靠存储的具体实现 |
| `DurableExecution` | 幂等、执行记录、任务接受/终态、未知副作用结果与恢复策略 | Workspace、Workflow 的具体实现 |
| `Workflow` | 有检查点的编排、步骤身份、恢复、重试与补偿 | Workspace；依赖 Durable 与共享 Automation 表达契约 |
| `DocumentWorkspace` | Project/Document、对象、Revision、事务、History、生命周期、原子编辑与状态恢复 | GUI、OCCT、Machine/CAM |
| `Control` | 本地请求协议、会话桥接、命令发现、任务/计划/日志控制、CLI 客户端 | 业务实现、强制 Workflow/Workspace |
| `Adapters` | JSON/Schema、TOML、日志、线程池、SQLite、文件/Hash、Named Pipe、MCP 等按项实现 | 未选择的其他适配器 |

`Contracts` 中的存储端口只表达执行记录和提交协作所需的最小能力；不建设通用 ORM、分布式事务或万能存储框架。需要原子关联的 Workspace 状态记录与执行回执，由一个窄的集成提交路径连接。

Workflow 使用 Automation 的公共表达式/步骤契约，但 Automation 通过可选窄端口引用 Workflow；Automation 不能反向强制链接 Workflow。没有安装 Workflow 时，包含该能力的计划在编译阶段拒绝。

### 2.3 四种正式 Profile

| Profile | 默认组合 | 典型用途 |
|---|---|---|
| `Embedded` | Foundation + Contracts + CoreRuntime + 所需基础适配器 | 新应用中的命令、查询、异步任务和日志；不要求文档和数据库 |
| `LocalAutomation` | Embedded + Automation + Control/CLI/本地 IPC | 外部 CLI/脚本控制常驻程序 |
| `DurableAutomation` | LocalAutomation + DurableExecution；可靠编排时增加 Workflow | 无文档但需要执行历史、幂等、重连和恢复 |
| `LaserCNC` | DurableAutomation + Workflow + DocumentWorkspace；领域模块另加 | CAD/CAM/加工产品的宿主 |

另外维护 Workspace 的内存组合测试，证明文档机制不必强制依赖 SQLite。组合数量保持有限，不要求测试所有布尔开关的任意排列；声明并验证允许的组件依赖矩阵。

### 2.4 裁剪必须真实生效

未选择组件时：不编译其源文件，不安装/传递其公开头，不下载其依赖，不链接其库，不创建其服务和后台线程，不迁移其数据库表，不在目录中声称其能力存在。

依赖缺失的模块在配置/注册期拒绝；不允许 Null 对象对必要功能返回假成功。可用默认内存记录和默认日志，但其能力必须如实标记为内存/非持久。

模块注册和执行定义冻结，不代表业务对象、会话、任务和运行状态冻结。运行期可变目录使用独立版本与寿命规则。

---

## 3. 公共契约与命令定义

### 3.1 核心身份

| 身份 | 语义 |
|---|---|
| `PrincipalId` | 经宿主认证的稳定调用主体，不是客户端任填字符串 |
| `SessionId` | 一次连接/交互会话，重连可变化 |
| `RequestId` | 一次传输/调用尝试，用于匹配响应，不等于幂等键 |
| `IdempotencyKey` | 主体和逻辑操作命名空间内的重试身份 |
| `TaskId / WorkflowId / PlanRunId` | 运行实例的稳定身份 |
| `TraceId / SpanId` | 可观测性关联，不提供权限 |
| `ResourceId / ExecutionGroupId` | 受管理资源与寿命分组，不用 ProjectId 冒充通用概念 |
| `TargetRef` | 有注册类型与稳定身份的目标引用，由可信目标解析器解释 |

Core 不硬编码 Project/Document 层级、不定义 Geometry/Cam/MachineContext 修订枚举。Workspace 把目标与修订解析成自己的强类型对象。协议中的扩展参数必须有注册 Schema 和处理器，不是任意字典或 `void*` 状态后门。

请求方可提出更短截止时间/更小预算，不能提高服务器配额；生效预算取服务器政策与合法请求约束的交集。TaskId 等执行实例身份由 Host 生成或按严格唯一性协议准入。

网络请求只能提交未信任数据。认证边界创建不可由请求自行提权的 VerifiedCaller/授权上下文。C++ 进程内插件属于受信任代码，本架构不是针对恶意同进程代码的安全沙箱。

### 3.2 一个命令定义，两个视图

`CommandSpec` 是统一来源，分为：

**执行契约**：名称+版本、输入/输出 Schema、执行类别、同步/异步、权限、目标解析、资源/Guard 规则、重试/耐久策略、是否支持原子组合。

**语义资料**：摘要、使用场景、单位/坐标系/绝对相对含义、业务前置条件、影响范围、结果解释、错误处理、示例/反例、相关命令。

执行类别建议最初仅使用 `ReadOnly`、`StateMutation`、`ExternalEffect`、`Lifecycle`。设备运动、激光等分类在领域命令的权限、风险策略和 Guard 中表达，不进入 Core 枚举。

既不默认所有命令 DocumentWrite，也不默认所有命令都是“无害”。注册时必须明确类别和所需保障；校验 handler 形态与声明一致。

### 3.3 Handler 与业务服务

Handler 是入口适配器，不是其他业务实现的复用入口。推荐：

```text
Command Handler -> 类型化业务服务 -> 算法
Atomic Binding  -> 同一个业务服务 -> 算法
Task Stage      -> 同一个业务服务 -> 算法
```

一个高层命令可连续调用很多算法，不需要每个算法再走 Registry、JSON、权限或事务入口。但仍处于这次操作已有的授权、资源、取消和提交边界内。

业务逻辑不得从 Registry 取出其他 handler 作为执行旁路；通用原子引擎可以在校验后使用框架内部绑定调用，但不向业务代码开放该通道。

### 3.4 版本与值规则

命令、查询、任务定义、脚本/计划格式、Workflow 定义、持久格式分别版本化。首版可靠自动化优先精确版本；兼容解析只能在明确的兼容规则内选择，执行接受时保存实际解析版本与定义指纹。

Registry 已有定义不原地变更；变更新版本。未知类别、字段策略、未来格式、无效枚举默认拒绝，不能猜测含义。

SDK 的 `uint64` 修订/序列值在 JSON 中使用明确的十进制字符串，避免客户端数字精度差异。运行期 deadline 使用单调时钟；传输提交超时时长或有规则的绝对截止时间，持久化不保存 `steady_clock::time_point` 原值。

Input Budget 必须在完整构建深层 Value 之前由解析器执行。Schema 引用只解析随包/注册提供的资源，首版禁止校验时从任意网络 URL 下载 Schema。

---

## 4. 执行模型与治理

### 4.1 固定执行绑定

在注册/冻结期生成 `ExecutionBinding`：解析器、编译校验器、目标解析器、权限规则、必要资源/Guard、具体执行适配器和结果策略均固定。

热路径只做必要的绑定查找与动态检查。不逐请求构造无限中间件链，不逐步骤扫描所有服务，不把每个政策包装成新的堆对象。窄虚接口/函数绑定允许使用，但数量和成本必须测量，不能宣称静态库自动等于零开销。

目录/文档是冷路径。执行使用稳定引用或已校验 handle；每次请求不得深拷贝完整命令目录、长说明和全部 Schema。进程内 handle 带所属 Registry 世代，不作为持久身份或对外权限票据。

### 4.2 正常执行链

```text
输入预算/协议检查
 -> 认证主体 + Host 准入
 -> 解析已注册版本/绑定
 -> 参数 Schema + 粗粒度授权
 -> 可信目标解析、归属和动态前置条件
 -> 取得对应活动/资源租约
 -> 在保护边界内复核授权与敏感条件
 -> 执行、校验与提交策略
 -> 形成事实回执
 -> 事件/日志/Trace 观察
```

不同类别允许采用经审计的细分顺序，不用一个任意可插入的公共管线覆盖一切。数据读取之前必须完成足够的权限与归属检查；危险操作不能只在等待资源之前检查一次 Guard。

对于外部副作用：必要资源与 Guard 复核、持久 claim 必须先于真实动作。可能变化的业务安全条件在实际执行附近再次核验，必要时由设备层持有有效 permit；Host 的一次检查不是实时安全保证。

### 4.3 结果不是只有成功/失败

回执区分：

- **执行阶段**：Rejected / Accepted / Running / Completed；
- **业务结果**：Succeeded / Failed / Cancelled / Stale 等；
- **修改事实**：NotApplied / Applied / Indeterminate；
- **证据状态**：Volatile / Persisted / PersistenceFailed 等。

具体 DTO 可以使用互斥变体和组合字段，必须限制合法组合，避免任意笛卡尔积。`Result/Error` 继续用于可恢复失败；不能仅靠一个 Error 隐去“动作已发生”。

只读结果 Schema 不合法可拒绝返回；状态写结果必须在正式提交前校验。外部动作已发生后输出 Schema/日志失败，要保留 Applied 或 Indeterminate 事实，不能假装动作未执行并诱导自动重试。

### 4.4 生命周期操作

Workspace create/open/close 与运行普通编辑不同。它们由 Workspace 注册的固定受治理绑定执行，Core 不写 ProjectCreate/DocumentOpen switch。

普通活动租约与生命周期转换许可区分，避免 close 被自身租约阻塞。只允许可信注册绑定申请对应转换许可，客户端没有 skipAdmission、skipPolicy、trusted=true 等开关。

### 4.5 唯一公开业务入口

GUI、CLI、Script、AI 和普通跨模块业务写入均进入同一受治理入口；读取按查询服务契约处理。内部算法只读计算可以直接调用类型化服务。

系统任务管理、目录发现和日志查询也属于有授权的系统服务，不因不是 CAD 命令就绕过身份与预算检查。

统一网关不意味着 Core 的头文件包含所有扩展 DTO。plan.run、workflow.resume、workspace.open 等由已安装扩展注册为系统命令/查询；Core 只处理通用请求及内置任务契约，Control 按实际装配投影协议面。

---

## 5. Host、模块与线程寿命

### 5.1 启动

```text
Configuring
 -> 验证完整组件与模块依赖 DAG
 -> 受治理注册，注册错误不能被模块吞掉
 -> 校验 Schema/版本/执行绑定/组件要求
 -> 存储独占与组件迁移、恢复验证
 -> 初始化并准备模块
 -> 冻结注册和服务装配
 -> Ready，开放外部准入
```

启动失败按已参与范围逆序清理，保留原始失败和清理失败。所有 Ready 前恢复材料都先验证，不调用历史 handler 或投递历史事件驱动设备动作。

`ModuleContext` 只提供模块确实需要的服务、注册和寿命契约，不交付完整产品 AppKernel。模块不把 ServiceRegistry 当任意动态全局变量表；稳定服务在初始化阶段解析并保存合法引用。

### 5.2 停止

```text
Ready -> Draining
  封住新业务、任务与计划的接受
  保留有授权的诊断、查询与取消控制
  请求已有工作协作取消/按既定策略完成
  等待业务提交、完成回调和必要记录发布
  确认执行器排空
  停止模块与观察器
  释放存储独占
  -> Stopped
```

停止等待超时：返回未完成清单，保持依赖存活；不能将未结束线程报告为已结束。析构需要最终寿命屏障，必要时可以阻塞；无法保证的非法析构应明确拒绝/终止，而不是 detach 后释放依赖。[R3]

已经接受的任务若需要提交候选结果，只能通过预先定义的受治理完成路径；不得以“内部调用”名义在 Draining 期间启动新业务。每类任务明确选择停止时放弃未提交候选，或允许已有提交完成，不临时扩大权限。

不支持从所属 worker 销毁 Host，不允许锁内调用用户 handler/exporter，也不允许 worker 同步等待必须依赖同一饱和线程池才能完成的子任务。用延续/事件推进等待，避免线程池自死锁。

高层 close 与低层资源释放分开。GUI 关闭窗口不等于自动销毁仍被任务使用的运行时。

---

## 6. Task、资源、取消与背压

### 6.1 任务职责

TaskRuntime 负责定义校验、接受、所有权、快照、进度、取消、结果和终态。Scheduler 负责 ready/dependency/priority/resource 决策；ITaskExecutor 只执行已准入的工作及完成回调，不负责业务状态和持久化。

保留线程池适配器，不默认叠加第二套 Taskflow/线程池。设备 I/O 与 CPU 长计算可有独立执行器，但受同一资源和寿命治理。

建议任务主状态：Pending/Ready/Running/CancelRequested/Succeeded/Failed/Cancelled/Stale；恢复状态通过独立恢复处置或严格映射表达 Interrupted/Indeterminate，不伪造成正常完成。

### 6.2 必须区分的边界

| 现象 | 实际语义 |
|---|---|
| 返回 TaskId | 请求已接受；要求持久时已形成相应持久接受证据 |
| wait 超时 | 客户端停止等待，不等于任务失败或取消 |
| cancel 返回 | 已收到取消意图，不等于工作已停止 |
| 客户端断开 | 按明确任务寿命策略处理；默认宿主任务不会因 CLI 退出消失 |
| 计算成功 | 不自动等于结果已应用到业务状态 |
| 业务完成 | 终态记录或完成回调可能仍需收尾 |
| stop 超时 | 不授权提前释放模块、状态或存储 |

已经完成真实副作用或提交的操作，不得因为稍晚到达的取消请求把结果改成“从未执行的 Cancelled”。纯计算可以在取消后丢弃候选；外部动作要保留已执行/不确定事实。

### 6.3 资源模型

使用由可信绑定解析出的 `ResourceId + Shared/Exclusive + units`，资源别名必须归一到同一身份。ProjectRead/Write 不再是 Core 类型，Workspace 将二者映射为同一个资源的不同访问方式。

多资源一次原子获取，避免持有部分后无界等待。不得允许调用者通过随意换 resource key 绕开同一设备互斥。未知资源默认拒绝或由注册的资源工厂受治理创建，不能静默生成无限资源槽。

准入与 release 使用可移动 RAII Lease，租约只释放自己实际获得的声明。容量累计检查溢出；运行期调整容量要有明确治理，不允许冻结定义后任意变更。

### 6.4 有界与公平

任务队列、每主体并发数、依赖数量、结果保留、日志/事件队列、变量数据和持久回执均有预算。满载返回 Busy/QueueFull/QuotaExceeded，不能无限积压。

控制请求保留独立预算：取消、任务查询、Host 停止不能被正常工作队列完全挤占。但软件取消队列不代替硬件急停。

Scheduler 的 ready 工作结构与历史结果分开，历史变多不应使每次调度都线性扫描全部终态。先保留已验证调度规则，再以测试和基准单独优化数据结构；避免在迁移中无证据地全面改算法。

### 6.5 长算法模式

```text
一次高层请求
 -> 捕获输入与相关版本
 -> 一个受管理任务内连续执行算法阶段
 -> 形成候选结果/DataRef
 -> 短的受治理 apply 操作复核版本并提交
 -> 高层任务形成最终结果
```

低层“仅计算”任务可返回计算结果；对外承诺“生成并应用”的高层任务，只有 apply 完成才报告该承诺成功。无需新增独立 JobRuntime，使用任务阶段/已定义的编排表达即可。

## 7. DocumentWorkspace 与原子组

### 7.1 Project 与 Document 的位置

Project 管稳定身份、归属、目录和生命周期，允许 0:N 文档；Document 管对象状态、一致性快照与编辑历史。工程清单、加工配置、机台包和发布格式属于上层业务，不塞进 ProjectRuntime。

Document 是逻辑状态容器，不等于输入文件、模块、视图或一个 STEP 模型。设备连接、实时位置和实时告警也不是可用普通文档 Undo 撤销的状态。

Workspace 内保留 DocumentStore、事务、History 和生命周期的一套状态真相。其他业务状态不强制套 Document；由其状态组件提供一致性实现。

### 7.2 修订与状态提交

通用 Revision 表达单调版本；Geometry/Cam/MachineContext 等修订域由领域文档类型声明，并在装配期绑定为有界槽位。不要把这些名称重新放回 Core。旧 LaserCNC RevisionSet 的字段/顺序/历史语义通过 Workspace 的迁移映射承接；迁移不能重置非零项目修订。

首轮迁移不同时全面改成 COW/MVCC。保留按值/不可变快照与候选编辑语义，再按真实容量测试决定优化。后端换实现不应改变公开的一致性与版本前置条件。

状态写入顺序：建立候选 -> 校验结果与完整候选 -> 检查基准修订/归属 -> 准备无失败安装材料 -> 持久提交（启用时）-> 安装内存状态/History -> 发布成功事件。

持久 commit 已成功而之后内存安装异常，必须报告已提交或进入隔离恢复，不能声称已 rollback。提交后的观察错误不反转业务结果。

### 7.3 原子组与顺序脚本分开

| 能力 | 提交语义 | 性能含义 |
|---|---|---|
| 单条命令内部批量操作 | 同一个业务命令共享状态事务 | 优先采用，基础已经存在 |
| 顺序 Script/Plan | 每步按自己的命令语义执行，可能分别提交 | 减少模型与 IPC 往返；可循环正式命令入口 |
| AtomicGroup | 兼容操作共享一个候选状态，最后一次应用提交 | 减少重复快照、提交与组级边界处理 |
| 数据库物理 group commit | 多事务共享部分 I/O 同步成本 | 不属于首版，不等于逻辑原子组 |

JSON-RPC batch 是传输请求集合，不承诺顺序或事务原子性，不能替代 AtomicGroup。[E1]

### 7.4 首版 AtomicGroup 的固定约束

1. 单一状态提供者、单一现存 Document，参与操作明确注册为可组合。
2. 只包含可回滚的状态操作及读取同一候选状态的组内查询。
3. 不包含真实设备动作、外部文件发布、网络写、生命周期 create/open/close、等待 Task/人工/AI、跨文档写和嵌套原子组。
4. 操作数、输入量、候选内存和协作时间预算有界。不能用永久打开的远程事务跨多次 AI 对话。
5. 所有子步骤使用受限 EditSession，不具有 commit/rollback/持久 SQL 权限；组协调器唯一提交。
6. 计划静态预检不能替代引用代入后的 Schema/目标检查。不得只授权 batch.execute 而绕过子操作权限。
7. 默认一组形成一个 Undo 单元；要求整组可撤销时，含不可撤销操作在预检中拒绝。明确允许 barrier 的业务政策可以另行声明，但不得谎称可撤销。
8. 中间步骤只报告候选进度，不报告已提交成功。失败放弃候选；整体成功才发布状态和业务成功事件。

原子组不是自动合并任意相邻命令。自动融合会改变中间状态可见性、错误位置、事件顺序和撤销边界，首版禁止隐式优化。

### 7.5 原子组执行链

```text
解析计划/展开有界结构
 -> 精确解析所有命令版本并检查可组合声明
 -> 检查输入、目标、所需能力与组预算
 -> 获得目标活动租约，捕获基准修订
 -> 一次候选状态/EditSession
 -> 逐步绑定参数、验证真实权限和目标
 -> 通过可信绑定调用共享业务操作
 -> 后续组内查询读取候选状态
 -> 复核授权世代、归属、全部必要修订及完整候选
 -> 一个状态提交 + 相应幂等结果/History
 -> 提交后事件和组级结果
```

权限可能在执行期间被撤销时，以声明的授权策略在敏感步骤及提交边界重新核验；初始权限集合不是永久许可。活动租约保护对象寿命，不代替权限。

整个原子组只有组级幂等边界，不给尚未提交的子步骤保存独立“已成功”记录。组签名覆盖步骤顺序、解析版本、输入、目标、前置条件和定义身份。

### 7.6 高频批量与算法复用

优先提供 `translateMany`、`createPattern`、`setProperties`、`generateToolpath` 等业务批量命令，复用同一类型化服务。不要在 translateMany 内循环 executeCommand(translate)。

细粒度命令仍保留，供交互和临时组合；算法里的插值、向量运算、单点碰撞等不成为 AI 每点调用的命令。

N 次单命令、一个 N 操作原子组、一个专用批量算法，是三个不同测试项；不能保证后两者消除全部逐项校验或算法成本。

### 7.7 大数据与资产寿命

不可变资产按内容身份/不可覆盖文件键存储。先写临时材料、flush、原子发布，再提交引用索引；允许未引用孤儿文件，不允许正式状态引用不存在材料。

GC 根至少包含活动状态、History、快照、未完成执行、任务结果、Workflow 检查点、迁移和活动读取租约。不能把某个对象删除等同于立即删除其历史仍使用的资产。

DataRef 的位置不是任意文件路径授权。打开时验证调用者、存储根、大小和内容身份；公开对象 ID 不直接用作磁盘路径。

---

## 8. Automation：一套 Script/Plan，多个执行边界

### 8.1 不建设三套重复引擎

Script 是程序化表达；Plan 是一次提交的已编译/待执行计划；Workflow 是需要持久检查点的编排实例。三者复用命令、表达式、结果引用和节点验证契约，不各自再写一套控制流语法。

保留现有 AST 中 Assign、Assert、If、ForEach、Include、Call/Query、Wait 的能力，解开其对 DocumentRequest 和具体 Workflow 实现的强制依赖。[R5]

首版规范形式采用 JSON 结构化计划。人类可读 DSL/REPL 只是到同一 AST 的前端，后续按需求增加；不默认嵌入 Bash、Python、Lua 或 JavaScript VM。

### 8.2 节点与限制

- 顺序 Call/Query：进入正式执行管线，各自保留提交边界。
- Assign/If/Assert/ForEach：只操作有界计划变量，不直接访问 OS、数据库或活动状态。
- Wait：通过宿主事件/延续推进，不占着 worker 阻塞等待。
- Include：精确版本、定义指纹、循环检测与深度限制。
- AtomicGroup：转交已装配状态提供者，使用第 7 节的严格子集。
- Parallel：首版不必提供；后续只在显式独立的只读/任务分支和资源规则下扩展，不能让同一 EditSession 并发修改。

Retry 不是默认控制流。只有明确可重试的读取、计算或有去重/对账保障的步骤才能有限重试；未知设备副作用禁止盲目自动重跑。

### 8.3 临时计划与注册冻结

已注册 Script 是稳定版本化能力。AI 临时提交的计划是**不受信任输入数据**，经固定编译器校验后执行，不向冻结 Registry 临时插入命令或 handler。

编译结果绑定精确命令版本与 Registry 身份；结果引用仅允许受限路径和明确类型，拒绝循环/未定义步骤/不合法路径/缺字段，禁止把引用表达式当任意代码求值。

编译缓存有容量上限，缓存结构与 Schema 解析，不永久缓存授权或当前状态许可。

### 8.4 示例：同一文档原子编辑

下列命令与 JSON 格式是本设计的示意契约，CAD 命令并未因此在当前仓库实现。

```json
{
  "format": "portable.plan.v1",
  "mode": "atomic",
  "target": {"type": "workspace.document", "id": "document.example"},
  "preconditions": {"workspace.projectRevision": "42"},
  "steps": [
    {
      "id": "base",
      "command": "cad.polyline.create",
      "version": "1.0.0",
      "arguments": {
        "points": [[0, 0, 0], [20, 0, 0], [20, 10, 0]],
        "unit": "mm",
        "coordinateSystem": "document"
      }
    },
    {
      "id": "offset",
      "command": "cad.curve.offset",
      "version": "1.0.0",
      "arguments": {"distance": 5, "unit": "mm"},
      "bindings": [
        {"argumentPath": "/sourceId", "fromStep": "base", "resultPath": "/objectId"}
      ]
    }
  ]
}
```

`preconditions` 由该目标/操作的注册 Schema 解释，不是任意标志。Bindings 注入后的完整 arguments 再通过命令 Schema。引用的是候选组内结果，不暴露未经提交的活动状态。

### 8.5 验证、预览与提交

`validate` 检查结构、版本、权限需求、引用、组合限制和预算；不执行真实副作用。

`preview` 只对明确提供纯计算/隔离候选实现的命令开放，输出预计变更和输入版本，不以真实执行后回滚代替。

`run` 重新执行动态授权、归属、修订与资源检查。预检/预览结果不是权限票据，不保证之后仍可提交。

不得把 AI 的思考间隔包含在事务寿命内。交互确认时保存候选计划和版本信息，确认后建立新的有界执行。

---

## 9. DurableExecution 与恢复

### 9.1 内存执行与持久执行

Core 的内存模式可以提供本进程有界结果和去重，但必须标明失效范围。声明需要持久接受/副作用记录/跨重启幂等的操作，未装 Durable 时应拒绝注册/Ready，不能静默降级。

Durable 包含执行回执、幂等 claim、Task 接受/终态、ExternalEffect 的 Executing/Completed/Interrupted/Indeterminate/ReconcileRequired 等事实。Workflow 检查点由 Workflow 组件通过其端口写入，不迫使所有 Durable 消费者链接 Workflow。

### 9.2 存储所有权与事务边界

一个数据库只有一个活动写 Host；独占要在迁移、恢复或 abandoned claim 修正之前取得，并持续到所有任务/模块排空后才释放。[R4]

执行记录、Workspace 状态和 Workflow 可有不同服务，但需要共同原子的写操作使用**同一个数据库连接事务所有者/提交协调器**。处理器不能拿裸 SQL 随意提交。

以下边界必须保留：

| 行为 | 同一原子边界中写入 |
|---|---|
| 文档写命令/原子组 | 状态 Journal、对应幂等结果与必要 History/Outbox 材料 |
| 异步接受 | Task 接受事实及命令接受回执/幂等绑定 |
| Workflow 检查点 | 该检查点的状态、步骤身份与已完成事实 |

外部设备动作不在 SQLite 事务中。只能在动作前保存 durable claim，再记录可证明结果；崩溃窗口保留不确定性，不承诺一般化 exactly-once。[E2]

### 9.3 幂等身份

逻辑键至少限定稳定 Principal、产品/操作命名空间及 IdempotencyKey。签名覆盖命令与解析版本、规范化参数、目标、前置条件和计划指纹；不把 RequestId、TraceId 或短期 Session 当成业务等价性。

重连的同一主体使用相同逻辑键可以查询已记录结果。不同主体不得利用相同字符串键窃取结果。每次重放读取仍核验当前权限和所有权。

兼容版本解析的重试先对照已接受的原版本/签名；不能因为 Registry 多了新版就把同一键重新解释成新操作。

去重保留有公开重试窗口。窗口内保证记录/墓碑未被不安全回收；过期重试明确拒绝或要求新的显式业务意图，不能删记录后把老请求悄悄当新请求。Task、Workflow、History 和资产引用共同约束 GC。

旧签名含 Session 等字段时按旧 codec 读取和迁移，不通过删字段伪造新格式等价性。

### 9.4 恢复规则

恢复先验证格式、大小预算、摘要、稳定身份、归属、修订链、快照锚点和组件要求，再安装状态。

恢复不自动调用历史 handler，不自动重新发布历史业务事件以驱动设备，不自动重开所有文档。未确认完成的纯计算任务标为 Interrupted，外部动作按策略进入 Indeterminate/ReconcileRequired；Workflow 恢复为可检查的暂停实例，经明确 resume 与当前准入检查后推进。

丢失组件材料不自动补造。裁剪 Host 遇到已有全功能库，默认拒绝可执行打开；可提供独立只读检查工具，保留未知材料。负责该格式的可信组件/迁移器未安装时不得“尽量恢复”。

### 9.5 SQLite 配置

先承接现有已验证配置及读回检查，再单独评估 WAL。不能把切 WAL 当作架构拆分的隐含步骤，也不能关闭刷盘获得好看的性能结果。

WAL 与 FULL/NORMAL 的耐久差异由 SQLite 明确定义；声明强耐久配置时要设置并验证实际生效值。跨数据库文件、网络文件系统和物理断电结果不从单机测试推导。[E3]

### 9.6 完整性不是对抗性认证

内容摘要能检查材料是否与已记录摘要一致，不能阻止能同时修改内容和摘要的攻击者。受信任本地存储根、访问控制、文件所有权和组件来源是另一层边界；不将 SHA-256 校验叫成安全签名或设备安全证书。

第三方工程包/设备包若需要对抗恶意篡改，应在领域导入边界另行使用签名/信任策略并做输入验证；不把此功能伪装成已有本地 hash 的自然保证。

---

## 10. 事件、日志、审计与可观测性

四种语义分开：

| 通道 | 责任 | 失败策略 |
|---|---|---|
| Domain Event | 已提交业务事实 | 只有提交后产生；需要可靠交付时使用相应持久机制 |
| Notification | UI/进度/缓存失效提示 | 可按明确键合并，慢消费者有界 |
| Log/Trace/Metric | 诊断与性能观察 | 默认隔离失败，不反转已提交业务结果 |
| Durable Audit/Execution Record | 必要的执行与恢复证据 | 若声明必须有，动作前失败应阻止执行；动作后失败保留真实事实 |

EventBus 只认识通用信封和投递规则。Workspace 通过可信提交发布端口附加自己的版本化元数据，不让 Core 包含 DocumentRevision。

不在 EventBus 锁内回调外部订阅者。业务事实不按 UI 合并策略随意丢弃；事件类型不同，预算与可靠性策略不同。

Core 的内存 EventBus 不承诺跨断线/重启不丢消息。需要可靠订阅时，Durable 可以提供 Outbox 子能力：与状态同事务写入，按至少一次交付，消费者按 EventId 去重。重投是事件交付，不是命令重放；未装该能力不得宣称持久订阅。

日志有结构化请求/任务/计划关联。大型参数、秘密、认证 token 默认不完整写日志。Metrics 使用低基数标签，不能把每个 RequestId、ObjectId 默认变成一条时间序列。

组执行保留一条主 Trace 和有界步骤信息；错误位置必须可查询，不为减少日志而删除必要审计。丰富命令说明与示例只走目录冷路径。

---

## 11. 本地 CLI 与协议

### 11.1 交付形态

常驻 Host 持有业务状态与任务。`lcnc` 是薄客户端，负责发现实例、请求编解码、输出与退出码；每次 CLI 连接不是启动另一套业务内核。

同进程调用直接进入 ExecutionGateway，不走 IPC。外部计划一次提交后在宿主内连续推进，减少模型与工具往返。

首版 Windows Named Pipe，显式 DACL、受控实例名称、禁止远程客户端、验证对端身份。Windows 文档表明默认安全描述符可能给予超出预期的读取权限，因此不能直接把默认值当安全政策。[E4,E5]

### 11.2 协议约束

请求/响应封装可采用 JSON-RPC 2.0，另行定义稳定的产品协议版本、任务方法和计划格式。JSON-RPC 自身不提供认证、原子组、任务寿命或业务取消。[E1]

长度前缀或明确帧边界先检查大小，再读完整 payload。处理分片、部分读写、非法编码、超时和连接关闭。状态修改必须有可匹配的请求与结果，不能用无响应通知承接需要恢复判断的动作。

控制请求与日志流分别有预算/优先级，慢日志消费者不能堵住取消和查询。进度流有 sequence/cursor 与显式 gap，断线后最终状态仍可查询；不声称易失进度一定能够补齐。

### 11.3 建议 CLI 形态

下列是目标接口，不是当前命令：

```text
lcnc host info --json
lcnc commands search "批量变换" --json
lcnc commands describe cad.translateMany --version 1.0.0 --json
lcnc command run cad.translateMany --version 1.0.0 --args-file args.json --json
lcnc plan validate --file plan.json --json
lcnc plan run --file plan.json --json
lcnc task get <task-id> --json
lcnc task wait <task-id> --timeout-ms 5000 --json
lcnc task cancel <task-id> --json
lcnc logs follow --task <task-id>
```

建议退出码按协议固定：正常获得成功响应为 0；用法/输入错误、拒绝、业务失败、等待超时、通讯失败分别不同。未使用 wait 的提交返回 0 只表示接受成功，不表示后台任务完成；机器消费者仍以结构化响应为准。

JSON 模式 stdout 仅机器结果，诊断 stderr。流模式单独声明 JSONL 格式，不能夹杂人类日志。大输入优先文件/标准输入，避免命令行转义和长度限制。

### 11.4 身份与权限

任务、计划、Workflow、日志、结果引用的 list/get/wait/cancel 都校验主体与归属。客户端传入的 PrincipalId/capability/approval 标志不能直接被接受。

同一 OS 用户下的 AI 和人工不天然是两个安全主体。需要区分时使用经可信宿主发放的不同 capability 会话，并由受信任界面/操作者产生有时效、绑定计划摘要/目标/版本的批准；不让 AI 自己声明 approved=true。

批准不替代机器安全条件，批准后目标/修订改变需要重新判断。远程网络控制、TLS、跨机身份和服务发现不在首版，后续保持相同受治理入口。

---

## 12. AI 命令资料与接入

### 12.1 “目录 + 语义 + 实例 + 实时事实 + 校验”

每个命令须有稳定名称/版本、输入输出 Schema、用途和不适用场景、目标身份、单位/坐标系/绝对相对语义、执行类型、风险/权限、取消/重试、原子兼容、输出阶段及可操作错误。

业务操作天然幂等与框架幂等去重必须分开。例如相对平移重复执行会再次改变状态，即使请求可通过幂等键去重，也不能描述成天然幂等。

实时对象 ID、当前修订和设备状态通过 Query 获取，不写成静态提示词中的事实。不得让 AI 用工程树序号或猜测的 ID 代替稳定身份。

### 12.2 一份定义多种投影

```text
CommandSpec + CommandDocs + Tested Examples
    -> CLI help / JSON catalog
    -> Markdown reference / 编辑器补全
    -> MCP tools / 其他模型函数工具定义
    -> 参数验证与文档一致性测试
```

MCP 提供工具发现、说明、输入/输出 Schema 等接口，适合做边界适配；核心不包含 MCP 协议类型，也不固定于某个模型厂商。[E6]

模型接口的 Schema 子集不同，转换器必须检查是否可无损表达。不能为适配模型而削弱服务器契约；不支持时改用受校验计划文件或报告不支持。

严格函数调用可以提高结构符合性，但不验证对象存在、授权、版本、新鲜度或机床安全；服务器仍执行全部动态检查。[E7]

### 12.3 渐进发现

小目录可以完整提供；大目录先给命名空间/摘要和搜索，再按需加载命令卡及具体 Schema。不要一次塞数千条完整说明，也不要只留一个没有参数资料的 invoke(name, arbitraryJson)。

目录区分 installed/visible/currentlyEligible。目录指纹、组件列表和命令版本支持缓存失效；它们不是权限票据。对外目录必须投影当前裁剪 Profile，不能显示未安装功能可执行。

实际流程：发现能力 -> 查状态 -> 查精确命令卡 -> 生成计划 -> validate/preview -> 根据权限提交 -> 查询任务与结果。

### 12.4 建议资料目录

```text
docs/automation/
  overview.md              # 能力边界、如何发现与使用
  concepts.md              # 身份、单位、坐标、状态和提交语义
  plan-format.md           # 一套计划语法、引用、原子边界
  execution-semantics.md   # accepted/completed/取消/重试/未知结果
  examples/                # 经测试的正常与错误样例
  commands/                # 从统一定义导出的命令参考
AGENTS.md                  # Codex 开发规则，不作为运行权限
skills/                    # 可选的任务型指引，不成为执行后门
```

AGENTS/Skills 用于指导 AI 使用或开发；不是运行时安全边界。至少用模拟客户端覆盖命令搜索、详情读取、正确计划、无权限、过时版本、错误引用、原子组禁止副作用等链路。实际 AI 工具适配另做端到端兼容测试。

不内置模型、不开放任意 OS shell、不把程序化工具调用服务当本地事务引擎。外部模型如何生成计划可以演进，业务程序始终验证相同契约。

## 13. 第三方依赖与工程交付

### 13.1 固定选择

| 能力 | 首版选择 | 放置位置与决策 |
|---|---|---|
| Value/Error/StrongId/Schema | 复用现有 Foundation | 不重造，不为换名称重写 |
| 日志 | spdlog | logging adapter，接口不泄漏 spdlog 类型 |
| JSON 与 Schema | jsoncons | serialization/schema adapter；预编译需并发验证 |
| 配置 | toml11 | TOML adapter，配置与计划格式分开 |
| CPU 执行后端 | BS::thread_pool | 保留当前加固后的 Executor 端口/实现 |
| 执行/状态元数据 | SQLite | 仅启用持久组件时取得与链接 |
| Windows Hash/本地文件 | 现有 BCrypt/文件适配器 | 维持端口边界，不假称跨平台 |
| CLI 参数 | CLI11 | 新增在 CLI 目标，不进入 Core 公共 API |
| 本地 IPC | Win32 Named Pipe | 有限本地范围使用原生适配；不先建设通用网络框架 |
| 测试 | Catch2 + CTest，现有故障/进程探针 | 每批组件与测试同步迁移 |
| 性能测试 | 复用现有基准并补尾延迟/批量；可选 Google Benchmark | 不要求为本次重构全面换测试框架 |

现有生产依赖已经按不可变提交/摘要固定，应承接锁定清单，不与架构重构同时升级。将现有一次获取全部依赖改为按选中目标获取。[R8]

CLI11 是现成的 C++ 命令行解析库，适合提供 argv、子命令和帮助解析；它不替代内部命令 Registry、权限、任务或事务。[E8]

首版不引入完整 CppMicroServices/CTK、第二个 Taskflow 调度层、通用消息中间件、嵌入 Python、完整 OpenTelemetry 栈或任意热卸载。Asio 等只有在确定需要多平台/多种 I/O 后再评估，不能因为“将来可能需要”成为强制依赖。

### 13.2 配置机制

配置值通过 Schema 校验后形成不可变配置快照，敏感字段有脱敏政策。基础组件提供配置加载/校验端口，TOML 只是默认编码。

执行定义、资源策略和存储耐久策略不允许无治理热替换。可热更新项（例如日志级别）明确注册更新规则与审计；首版不建设任意全局动态配置总线。

### 13.3 SDK 目录建议

```text
packages/
  foundation/
  contracts/
  runtime/
  automation/
  durable/
  workflow/
  workspace/
  control/
  adapters/
    jsoncons/  toml11/  spdlog/  bs_thread_pool/
    sqlite/  windows_storage/  named_pipe/  mcp/
apps/
  headless_demo/
  workspace_demo/
  cli/
schemas/
examples/
tests/
  unit/ contract/ integration/ crash/ performance/ install-consumer/
docs/
  architecture/ automation/ migration/
cmake/
```

物理目录不是架构验收。导出 `Runtime::Core`、`Runtime::Automation`、`Runtime::Durable`、`Runtime::Workspace` 等清晰 targets/components，并通过安装树消费者验证。名称是建议，可在首个契约检查点统一确定。

CMake 公共依赖、静态库最终链接所需依赖和可选组件必须正确导出，不能认为 PRIVATE 链接就让静态库的外部依赖自动消失。不导出开发机绝对路径；未选择组件不触发 find_dependency/FetchContent。[E9]

C++20 与当前依赖保持既有工具链组合；不承诺跨编译器/CRT 的二进制 ABI。发布前明确许可证、依赖许可证、支持平台、编译选项、版本与升级说明。

---

## 14. 性能设计与验收预算

### 14.1 三种开销分开测

1. **模型/工具往返**：一次提交一段计划减少交互次数。
2. **执行边界**：绑定、Schema、授权、租约、调度与观测开销。
3. **业务与状态**：算法、快照、候选验证、Journal、History、文件和恢复开销。

顺序脚本主要减少第 1 项；原子组减少可共享的第 2/3 项；专用批量算法能进一步共享计算。不能把它们混称为“Batch 自动零开销”。

### 14.2 热路径规则

同进程不回环网络、不 JSON 文本往返；CPU 算法内部不走命令或 AST。同步短命令不无条件投线程池，不增加全局串行队列。

Registry 冻结后使用稳定已绑定入口。Schema 在注册/计划编译时预编译，缓存覆盖内容身份/版本，验证并发安全。权限、对象状态与 Guard 不能因预编译被缓存为永远允许。

任务持有自己的有效输入寿命，避免反复深拷贝大文档；可逐步让 Workspace 的任务输入使用不可变快照句柄，但原有语义与寿命验证不能省略。不在新核心中大面积用 shared_ptr<void>/std::any 掩盖类型或转移责任。

观测记录容量有界；步骤 Trace 可配置采样/汇总，必要审计不能采样丢失。日志文件 flush 不进入所有内存命令路径。

不在同一个提交混合目录搬迁、状态存储算法改写、三方库升级和 LTO 配置变化。

### 14.3 等价语义基线

B 定义为当前固定 donor 提交在相同目标机、工具链、Release 选项、输入与保障条件下重新测得的基线。不能以 Phase 3（没有完整执行链）的速度代替当前执行语义，也不能把历史五个样本当 P99。[R9]

| 指标 | 初始预算（不是实测保证） |
|---|---|
| 同进程普通 Command/Query P50 | ≤ 1.05 × B |
| 同路径 P99 | ≤ 1.10 × B，必须有足够单次样本 |
| 相同固定负载吞吐 | ≥ 0.95 × B |
| 任务接受/开始/完成发布/取消响应开销 | 分别测量，尾开销增幅初定 ≤10% |
| 完整 Workspace 等价读写/恢复中位数 | 增幅初定 ≤5%，大状态与存储尾延迟独立记录 |
| 新增动态分配/全局锁 | 默认不新增无理由成本；例外需归因与预算 |
| 原子组 | 减少应用事务/候选构造次数，统计实际次数；不伪称只有一次物理 I/O |
| 外部 CLI | 单独建立端到端基线，不直接对比旧同进程调用 |

新身份检查等真实新功能应单列成本；不能通过去掉新要求或降低原保障达标。噪声大于门槛时改善测量，不能挑一轮最好结果。

### 14.4 测量矩阵

预热、多轮独立进程、A/B 交错、足够调用样本和分位区间，保留原始数据与提交/二进制/配置摘要。Google Benchmark 提供相应测试工具机制，但无需强制换库。[E10]

至少覆盖：

- 1/4/16 客户端；空/小/中/大参数；读/写/接受路径。
- 队列饱和、依赖链、资源冲突、慢日志订阅者、停止/取消竞态。
- 无文档/Workspace，内存/SQLite，1k/10k/100k 对象，长 Journal、多文档恢复。
- N 次单命令、顺序计划、单原子组、专用批量命令（N 可取 1/10/100/1000，超出原子预算的组应明确拒绝）。
- 执行入口次数、状态事务次数、候选构造、持久写次数、分配/内存峰值、锁等待与终态发布。

### 14.5 默认预算策略

结构中必须存在以下限制：请求字节/深度/元素数，计划节点/展开次数/引用深度，原子组步骤/候选内存，任务排队/并发/结果，订阅队列/日志保留，重试次数/幂等窗口。

可提供开发 Profile 的起始配置（例如计划展开最多 10,000 节点、Include 深度不超过 16、原子组最多 128 步），但必须标为可测初值而不是通用生产认证。实际支持上限由 M0/M8 容量测试确定。

deadline 是协作限制，不是抢占式杀线程承诺。超过软预算应取消/拒绝后续步骤并保留真实已执行事实；不可用无穷等待、无界分配或假取消掩盖预算问题。

---

## 15. LaserCNC 领域接入规则

Geometry/OcctGeometryEngine、Collision、Machine/Device Driver、CAM、Process 和 Qt UI 都在新核心之外，通过领域端口和适配器接入。

- **OCCT**：提供几何服务和私有几何资产；不把 TopoDS/TDF 类型放入通用命令或任务协议。若使用 OCAF 内部事务/历史，由几何适配层与应用事务协调，不暴露第二套平级全局 Undo。
- **CAM**：高层命令提交生成任务；任务内部类型化算法连续执行，候选刀路按版本复核后应用。
- **Collision**：安全域、连续路径认证等属于业务安全服务。通用内核仅提供任务、资源、前置条件和 Guard 端口，不认识特定机床几何。
- **Machine/Process**：设备状态与控制许可由相应服务拥有，真实动作采用 ExternalEffect 与设备层安全约束。普通文档 Undo 不倒转已经发生的运动。
- **UI**：按钮、命令行与树编辑调用同一业务入口，视图刷新采用 Notification；UI 无活动状态可变后门。

稳定厂商 SDK 可进程内适配；不稳定或可能阻塞/崩溃的驱动可后续独立 DeviceHost，以进程边界隔离。静态库不能提供恶意代码隔离或可靠强制终止阻塞调用。

---

## 16. 重构起点与复用矩阵

### 16.1 固定两个提交，各司其职

- `52b099a9e9cabfafe5a6c2c3e95f92c2e857ed03`：新分支/工作区的基础骨架。
- `432434f9c43d3f83c124ac1cf23fec39018f394f`：本轮 donor，实现、后续修复、测试和当前语义对照。

Phase 3 只是结构较干净，不等于其每个实现都优于 donor。明确迁移线程池排空、持久独占与相应测试。不全量 merge donor 回核心，不按旧 Phase 4 路线先把 Document 重新嵌入 Core。

工作区建议：原工作区不动；reference 固定 donor 并约定只读；portable 在 Phase 3 新分支开发。构建、测试数据库、快照、日志、IPC 名称各自隔离。

### 16.2 复用分级

| 级别 | 对象 | 处理方式 |
|---|---|---|
| A：近原样逻辑 | Foundation；JSON/TOML/日志适配；Windows hash；当前线程池执行器 | 接口/实现/测试一起迁入；构建与命名调整不等于算法重写 |
| B：窄接口调整 | ServiceRegistry、ExecutionAdmission、Capability 原语、本地观测、SQLite 后端和文件适配 | 核对新通用 ID、主体、寿命和目标依赖，保留机制 |
| C：中等改造 | EventBus、ResourceManager、Scheduler/TaskRuntime、命令注册器、Script/Workflow | 保留算法与故障语义，替换文档耦合和新契约；不能叫直接复制 |
| C：独立扩展迁入 | Document/Transaction/History/Project lifecycle、状态恢复 | 保留为 Workspace 一套状态真相，原子组增加受限编辑绑定 |
| D：重做编排 | AppKernel/Host、ModuleRegistrar、Gateway、具体生命周期分派、集中式 PersistenceService | 重画所有权与依赖，复用局部可靠逻辑与测试，不带回旧大对象 |
| 新增 | 命令语义资料导出、临时计划准入、通用原子组合、本地多客户端控制、MCP/SDK 发布 | 不把这些本来就要新增的成本全部算作旧代码返工 |

### 16.3 迁移记录

每个单元记录来源提交、接口与关联文件、后续修复、测试与行为不变量、实际差异、验证结果。不把来自多个阶段的不匹配接口、实现和测试拼在一起后只检查能编译。

早期文档保留历史，但新架构决策高于旧路线中“必须先做文档”的结构要求。正确性规则不能通过改文档取消。

旧数据优先通过明确兼容 reader 或前向迁移接入；确认无需产品级旧格式支持时也只能通过显式决策缩减，不能删掉恢复故障样本和原始材料。

---

## 17. 分阶段实施计划

| 阶段 | 交付范围 | 退出条件 |
|---|---|---|
| **M0 基线与规则** | 两个固定版本；来源/行为映射；补私有头与负例扫描；当前语义 Release 基线；新目标 ADR | 基线实际结果与未运行项清楚；不继承旧版本绿灯 |
| **M1 可裁剪骨架** | Foundation、Contracts、独立 adapter targets；新 Host/ModuleContext；组合依赖图；构建安装最小消费者 | 无 Workspace/SQLite 的安装树消费者编译通过；缺组件明确失败 |
| **M2 同步核心与目录** | Command/Query、身份/授权、固定绑定、Schema、事件/日志；CommandSpec/Docs 与 describe | 无文档真实命令可调用和发现；无效输入/权限/版本不运行 handler |
| **M3 无文档异步闭环** | Task/Scheduler/Resource、取消/进度/结果、队列预算、停止/排空；完整 actor/owner | 任务接受/取消/完成/析构竞态通过；达到第一轮性能预算 |
| **M4 顺序计划** | 复用 Script AST；临时计划校验与结果引用；不重复建语言 | 一次提交多步，部分失败保留真实已提交结果；预算与未知步骤拒绝 |
| **M5 Durable** | 内存/持久能力声明；执行记录/幂等/Task/Effect；独占和恢复 | 无文档数据库不建 Workspace 表；重连/崩溃不盲重放，副作用未知可查询 |
| **M6 Workspace + AtomicGroup** | 类型化目标/修订、事务/History/生命周期；受限 EditSession；原子组；旧数据承接 | 同文档组一次应用提交；任一步失败/过期修订/无权限不发布候选；持久与回执保持原子 |
| **M7 可靠编排与外部控制** | Workflow 检查点/补偿；Named Pipe、CLI、命令搜索/帮助、任务/日志控制；AI Adapter 合同测试 | 两个 CLI 进程控制同一实例；断线/取消/权限/慢客户端通过；不需要 GUI/模型即可运行 |
| **M8 性能、安装与最终冻结** | Profile 组合、安装树重定位、三配置/进程故障、容量、文档/Schema 一致性、基线 | 一个共享核心；必要正确性项闭合；相同语义性能预算与材料齐全 |

M3 是继续/调整决策点：如果仍靠假 Document、双 CommandRuntime 或空成功适配支撑，应先修正契约，不扩大迁移。

M4 与 M6 共用计划表达，M6 的状态提供者接口在 M1/M2 就冻结基本边界，避免先写死“每步独立事务”后再返工。CLI 传输与 AI 资料实现可在接口稳定后并行，但不能先绕过权限做演示再把安全留到最后。

已讨论的 C5（存储）、C6（API/预算/保留）、C7（容量/性能）、C8（门禁）和 ST1D（最终认证）分别映射到 M0/M1/M5/M8，不因改路线而消失。旧缺陷按行为迁移，不以旧编号完成率作为新目标完成度。

不复用旧人日估计为本版承诺。现在增加了命令语义目录、临时计划、通用原子组和外部归属等契约，M3 后按实际差异与验证成本重估；生成代码速度不是总工程量。

---

## 18. 验收矩阵与不变量

### 18.1 每个正式组合必须有的证明

| 测试面 | 必须证明 |
|---|---|
| 裁剪 | Core 无 Project/Document/RevisionSet/事务头；未选组件不获取依赖、不迁表、不显示能力 |
| 注册治理 | 重复/缺依赖/非法描述、吞注册错误、Ready 后变更被拒绝 |
| 身份 | 伪造主体、跨主体任务/日志读取、猜 ID、权限撤销不能越权 |
| 顺序计划 | 前步提交后后步失败，前步事实保留；停止后后续步不误执行 |
| 原子组 | 失败中间步骤、结果 Schema 错、修订冲突、持久失败、引用错均不部分发布 |
| 副作用 | claim 前拒绝、动作后结果未知、输出验证失败不假装未发生；不盲目重试 |
| 取消/寿命 | 排队、运行、提交边界、终态发布、Host stop 竞态；非协作任务不被假停止 |
| 资源 | 读写同槽、全部获取、冲突、公平、容量溢出和非法别名 |
| 恢复 | 单 Host 独占、真实进程中断、多阶段回执、旧格式、未知组件/损坏材料拒绝 |
| GC/保留 | 未完成 claim、Workflow/History/任务引用不会被回收；过期请求不复活执行 |
| 观测 | 慢/失败 exporter 不反转结果；必要审计失败不能被当成普通日志丢掉 |
| 发布 | 空工程仅用安装包、改变安装路径、无源树私有路径、静态依赖传递正确 |
| 性能 | 最终同提交、同语义、同配置采样，真实尾延迟而非五次均值 |

### 18.2 不可删减的行为原则

- 未注册、参数错误、权限不足、非法 scope/目标、缺必要组件的请求不调用 handler。
- 外部普通请求、内部脚本、复合命令和原子组不能存在不同的安全旁路。
- 原子组只有最终成功才发布状态/Undo 单元/业务成功事件。
- 成功提交与外部动作事实不能被日志失败、迟到取消或断线改写为“未执行”。
- accepted、computed、applied、durably recorded、executor drained 分开观察。
- 准入、租约、数据库独占和对象依赖的寿命顺序必须正确。
- 恢复不猜测设备动作结果；超时不等于没执行；幂等键不等于天然幂等。
- 目录/Schema/资料/计划预检不替代实时权限与业务安全条件。
- 不能为了性能去掉原子性、输入校验、记录和刷盘要求。
- 全部消费者使用一份核心实现，不形成长期新旧双内核。

---

## 19. Codex 开发约束摘要

将这些约束写进新工作区根 AGENTS.md，详细进度仅维护一份执行计划和测试映射。

```text
目标：实现本文件定义的可裁剪命令驱动运行时。
结构起点：52b099a9e9cabfafe5a6c2c3e95f92c2e857ed03。
固定 donor：432434f9c43d3f83c124ac1cf23fec39018f394f。
只修改专用 portable 工作区，不改 reference 和用户现场数据。

从新契约建立 Host 与执行边界，复用 Foundation/适配器及机制测试。
不全量 merge donor，不整包搬 AppKernel/集中 PersistenceService。
迁移单位是接口+实现+测试+行为约束，必须承接后续寿命/独占修复。

Core 不依赖 Project/Document、领域修订或第三方公共类型。
不靠假文档、空实现、void*/任意字典隐藏未解决的依赖。
模块静态组合，依赖 DAG 先验证；运行期不热卸载。
脚本/计划一套 AST；顺序执行与原子组明确分开。
原子组仅受兼容状态提供者治理，子操作无 commit 权限。
算法内部直接类型化调用，不逐函数或逐点进入命令系统。

每次只推进一个可验证检查点；文件搬迁、语义修改、三方升级分开。
先建立回归与正负样例，再替换对应执行链。
测试可按新结构改夹具，但必须保留原行为覆盖与失败材料。
不通过降低权限、恢复、取消、刷盘、事件事实保证提高速度。
不将未运行测试、旧报告或空示例写成新实现已通过。
每个检查点报告真实命令、退出码、完成标记、性能与剩余风险。
未经用户要求不强制清理、删库、改主分支、推送或合并。
```

本文件是目标设计，不要求一步生成全部组件。首批交付只到 M3：独立基础、命令与发现、真实无文档任务/日志/停止闭环。原子扩展接口同时有合同测试，再逐步接入实际 Workspace。

---

## 20. 完成定义

新项目只需链接选定组件、配置必要后端、注册业务命令及类型化服务，就得到统一的命令发现、执行、任务、日志与可选自动化/持久保障，不需要创建无意义的 Project/Document。

LaserCNC 则通过同一核心加 Workspace、Geometry、CAD/CAM、Machine/Process 和 UI 构建；没有平行执行入口、平行事务真相或另一套全局 Undo。

**最终完成条件：两个不同状态需求的真实消费者、一份共享执行核心、清晰的顺序/原子/外部副作用语义、实际裁剪和同语义性能证据。目录更整齐或测试数量更多都不能单独替代这些条件。**

---

## 参考来源与证据边界

仓库事实固定到下列提交；外部资料读取日期为 2026-09-05。公开规范用于论证边界，不表示建议功能已存在于仓库。源码方法名和新示例接口应据本文件的“已有/建议”标识区别使用。

### 仓库

- [R1] 当前 main 核对：https://api.github.com/repos/super1wang/LaserCNCv3.0/branches/main 。本次值为 `432434f9c43d3f83c124ac1cf23fec39018f394f`。
- [R2] Phase 3 交付（52b099a）：https://github.com/super1wang/LaserCNCv3.0/blob/52b099a9e9cabfafe5a6c2c3e95f92c2e857ed03/docs/阶段交付/2026-09-03-Phase3-Infrastructure-Adapters.md
- [R3] 当前 ITaskExecutor：https://github.com/super1wang/LaserCNCv3.0/blob/432434f9c43d3f83c124ac1cf23fec39018f394f/include/lasercnc/platform/task_executor.hpp
- [R4] 当前持久后端端口：https://github.com/super1wang/LaserCNCv3.0/blob/432434f9c43d3f83c124ac1cf23fec39018f394f/include/lasercnc/platform/persistence_backend.hpp
- [R5] 当前 Script AST：https://github.com/super1wang/LaserCNCv3.0/blob/432434f9c43d3f83c124ac1cf23fec39018f394f/include/lasercnc/runtime/script.hpp
- [R6] 当前命令执行：https://github.com/super1wang/LaserCNCv3.0/blob/432434f9c43d3f83c124ac1cf23fec39018f394f/src/runtime/execution/command_runtime.cpp
- [R7] 当前事务协议：https://github.com/super1wang/LaserCNCv3.0/blob/432434f9c43d3f83c124ac1cf23fec39018f394f/include/lasercnc/runtime/transaction.hpp
- [R8] 已锁定依赖：https://github.com/super1wang/LaserCNCv3.0/blob/432434f9c43d3f83c124ac1cf23fec39018f394f/cmake/Dependencies.cmake
- [R9] 当前基准源文件：https://github.com/super1wang/LaserCNCv3.0/blob/432434f9c43d3f83c124ac1cf23fec39018f394f/tests/benchmark/kernel_benchmark.cpp
- [R10] 未闭合计划：https://github.com/super1wang/LaserCNCv3.0/blob/432434f9c43d3f83c124ac1cf23fec39018f394f/docs/内核契约/ST1C-补充审计与剩余执行计划.md
- [R11] JSON/Schema 实现：https://github.com/super1wang/LaserCNCv3.0/blob/432434f9c43d3f83c124ac1cf23fec39018f394f/src/infrastructure/serialization/jsoncons/jsoncons_adapter.cpp
- [R12] 当前命令与描述符：https://github.com/super1wang/LaserCNCv3.0/blob/432434f9c43d3f83c124ac1cf23fec39018f394f/include/lasercnc/runtime/command.hpp

### 外部规范与官方文档

- [E1] JSON-RPC 2.0 Specification：https://www.jsonrpc.org/specification
- [E2] SQLite Atomic Commit：https://sqlite.org/atomiccommit.html
- [E3] SQLite PRAGMA / synchronous：https://sqlite.org/pragma.html
- [E4] Microsoft Named Pipe Security：https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-security-and-access-rights
- [E5] Microsoft CreateNamedPipe：https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-createnamedpipea
- [E6] MCP Tools：https://modelcontextprotocol.io/specification/2026-07-28/server/tools
- [E7] OpenAI Function Calling：https://developers.openai.com/api/docs/guides/function-calling
- [E8] CLI11 官方仓库：https://github.com/CLIUtils/CLI11
- [E9] CMake Importing and Exporting Guide：https://cmake.org/cmake/help/latest/guide/importing-exporting/index.html
- [E10] Google Benchmark User Guide：https://google.github.io/benchmark/user_guide.html

另已参阅当前对话原评估文件 `LaserCNC_Portable_Runtime_Refactoring_Plan.md`。本版明确新增/调整：Phase 3 结构起点、一套脚本表达、受限原子组、命令语义资料、取消后的副作用事实、完整性与对抗性认证区别、编排与持久组件的单向依赖。旧文档中的原工作量和执行分支建议不自动覆盖本版新增范围。
