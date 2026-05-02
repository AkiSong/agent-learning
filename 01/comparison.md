# 多Agent训练营01

## 裸 API vs OpenCode 对比体会

### 实验过程

- **裸 API 调用**：每次对话独立，无法访问文件系统，需要人工复制粘贴代码上下文，回答泛化且缺乏针对性。
- **OpenCode 编程**：能够自动读取文件、调用工具、保持会话状态，可以自主探索代码库并给出精准建议。

### 关键差异

- **文件访问能力**：裸 API 无感知，OpenCode 可读写文件、运行诊断
- **上下文感知**：裸 API 需人工传递，OpenCode 自动维护会话状态
- **建议具体性**：裸 API 基于假设，OpenCode 基于实际代码给出可执行方案

### 我对「无状态推理」和「有状态编排」的理解

无状态推理像问答机器人，每次请求独立处理，适合简单咨询。有状态编排像协作伙伴，理解项目结构、记住对话历史、主动探索，形成完整的认知闭环。后者的核心价值在于将静态知识转化为动态行动能力，使 AI 从"回答问题"进化为"解决问题"。

## 阅读 OpenCode 源码中的编排循环

### 观察（Observation）

runLoop 每次迭代开始时，会先读取当前环境的完整状态：
// packages/opencode/src/session/prompt.ts:1288-1304
let msgs = yield* MessageV2.filterCompactedEffect(sessionID)
let lastUser: MessageV2.User | undefined
let lastAssistant: MessageV2.Assistant | undefined
let lastFinished: MessageV2.Assistant | undefined
let tasks: (MessageV2.CompactionPart | MessageV2.SubtaskPart)[] = []
for (let i = msgs.length - 1; i >= 0; i--) {
  const msg = msgs[i]
  if (!lastUser && msg.info.role === "user") lastUser = msg.info
  if (!lastAssistant && msg.info.role === "assistant") lastAssistant = msg.
  info
  if (!lastFinished && msg.info.role === "assistant" && msg.info.finish) lastFinished = msg.info
  // ...
}
这里它从消息历史中逆向扫描，找出：
- lastUser：最近的用户输入
- lastAssistant：最近的模型回复
- lastFinished：最近一个已完成的模型回复
- tasks：待执行的子任务或压缩任务
然后检查终止条件（第 1316-1324 行）：如果上一次 assistant 已经正常结束（finish reason 不是 tool-calls），且没有待执行的 tool call，循环就退出。

### 思考（Thinking）

如果循环继续，就进入模型推理阶段：
// packages/opencode/src/session/prompt.ts:1392-1464
const handle = yield* processor.create({ assistantMessage: msg, sessionID, model })
// ...构建 system prompt、tools、messages...
const result = yield* handle.process({
  user: lastUser,
  agent,
  system,
  messages: modelMsgs,
  tools,           // ← 把可用工具注册给模型
  model,
  // ...
})
handle.process 内部会调用 llm.stream()（src/session/llm.ts:418），最终使用 Vercel AI SDK 的 streamText()：
// packages/opencode/src/session/llm.ts:336
return streamText({
  messages,
  model: wrapLanguageModel({ model: language, middleware: [...] }),
  tools,           // ← AI SDK 会根据 schema 让模型选择工具
  toolChoice: input.toolChoice,
  // ...
})
模型接收到历史消息 + 工具定义后，决定是生成文本还是调用工具。
### 行动（Action）

当模型决定调用工具时，AI SDK 会自动执行对应 tool 的 execute 方法。这些工具是在 resolveTools 中动态注册的：
// packages/opencode/src/session/prompt.ts:414-448
tools[item.id] = tool({
  description: item.description,
  inputSchema: jsonSchema(schema),
  execute(args, options) {
    return run.promise(
      Effect.gen(function* () {
        const ctx = context(args, options)  // ← 构建工具执行上下文
        const result = yield* item.execute(args, ctx)  // ← 执行实际工具
        // ...
        return output
      })
    )
  }
})
这里的 item.execute 就是 OpenCode 实际工具（如 ReadFile、Bash、Edit 等）的实现。工具执行是异步且并行的，由 AI SDK 管理。

### 更新状态（Update State）

模型输出的所有事件（文本片段、tool-call 开始、tool 结果、步骤结束等）都会以流的形式返回。processor 中的 handleEvent 负责实时更新消息状态：
// packages/opencode/src/session/processor.ts:216-461
const handleEvent = Effect.fnUntraced(function* (value: StreamEvent) {
  switch (value.type) {
    case "tool-call":
      // 工具开始执行：更新 part 状态为 "running"
      yield* updateToolCall(value.toolCallId, (match) => ({
        ...match,
        state: { status: "running", input: value.input, time: { start: Date.now() } }
      }))
      return
    case "tool-result":
      // 工具执行成功：更新 part 状态为 "completed"
      yield* completeToolCall(value.toolCallId, value.output)
      return
    case "tool-error":
      // 工具执行失败：更新 part 状态为 "error"
      yield* failToolCall(value.toolCallId, value.error)
      return
    case "finish-step":
      // 步骤结束：更新 assistant message 的 finish reason、cost、tokens
      ctx.assistantMessage.finish = value.finishReason
      ctx.assistantMessage.cost += usage.cost
      ctx.assistantMessage.tokens = usage.tokens
      yield* session.updateMessage(ctx.assistantMessage)
      return
  }
})
关键设计：工具执行结果（tool-result）会被写成新的 message part 存入 session。当这一轮 handle.process 返回后，runLoop 的 while (true) 会再次迭代，此时消息历史中已包含 tool 的执行结果，模型会在下一轮"观察"到这些结果，从而进入下一轮的"思考"。

当模型不再调用工具而是直接给出最终回答时，终止条件满足，while (true) 的 break 触发，Agent Loop 结束。