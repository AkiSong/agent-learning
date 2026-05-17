import type { Plugin } from "@opencode-ai/plugin"

export default (async ({ $ }) => {
  return {
    "tool.execute.after": async (input) => {
      const tool = input.tool
      if (tool !== "write" && tool !== "edit") return

      const filePath = input.args?.file_path ?? input.args?.filePath
      if (typeof filePath !== "string") return

      if (!filePath.includes("knowledge/articles")) return
      if (!filePath.endsWith("-enriched.json")) return

      try {
        const result = await $`uv run hooks/checkQuality.py ${filePath}`.nothrow()
        const stdout = result.stdout.toString().trim()
        const stderr = result.stderr.toString().trim()
        if (stdout) console.log(`[checkQuality] ${stdout}`)
        if (stderr) console.error(`[checkQuality] ${stderr}`)
        if (result.exitCode !== 0) {
          console.error(`[checkQuality] 质量检查失败 (exit ${result.exitCode}): ${filePath}`)
        }
      } catch (err) {
        console.error(`[checkQuality] 执行异常:`, err)
      }
    },
  }
}) satisfies Plugin