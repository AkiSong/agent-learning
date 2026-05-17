import type { Plugin } from "@opencode-ai/plugin"

export default (async ({ $ }) => {
  return {
    "tool.execute.after": async (input) => {
      const tool = input.tool
      if (tool !== "write" && tool !== "edit") return

      const filePath = input.args?.file_path ?? input.args?.filePath
      if (typeof filePath !== "string") return

      if (!filePath.includes("knowledge/raw")) return
      if (!filePath.endsWith(".json")) return

      try {
        const result = await $`uv run hooks/validate.py ${filePath}`.nothrow()
        const stdout = result.stdout.toString().trim()
        const stderr = result.stderr.toString().trim()
        if (stdout) console.log(`[validate] ${stdout}`)
        if (stderr) console.error(`[validate] ${stderr}`)
        if (result.exitCode !== 0) {
          console.error(`[validate] 校验失败 (exit ${result.exitCode}): ${filePath}`)
        }
      } catch (err) {
        console.error(`[validate] 执行异常:`, err)
      }
    },
  }
}) satisfies Plugin