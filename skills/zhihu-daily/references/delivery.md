# 邮件内容在工具之间传递

仅在用户触发日报/发送且配置 html_attachment 时发送，调试和改偏好不发送。

发现当前可调用的 Gmail send_email 后，在 functions.exec 使用下面代码。脚本负责收件人、标题、MIME、时效和重复交付检查。仅打印小量发送结果，不打印 HTML 或 MIME。

```javascript
const packet = await tools.exec_command({
  cmd: "python -X utf8 'skills\\zhihu-daily\\scripts\\pipeline.py' --workspace 'F:\\codexCoding\\dailyZhihu' mail",
  max_output_tokens: 100000
});
if (packet.exit_code !== 0 || !packet.output.trim().startsWith('{')) {
  text(packet.output); exit();
}
let request;
try { request = JSON.parse(packet.output); }
catch { throw new Error('Incomplete mail payload; do not send.'); }
const result = await tools.mcp__codex_apps__gmail_send_email(request);
const sent = result.structuredContent;
if (result.isError || !sent?.id) { text(result); exit(); }
if (!/^[A-Za-z0-9_-]+$/.test(sent.id)) throw new Error('Unexpected message ID; record manually.');
text({sent:true, recipient:request.to, message_id:sent.id});
text(await tools.exec_command({
  cmd: "& 'skills\\zhihu-daily\\scripts\\run.ps1' record --message-id '" + sent.id + "'",
  max_output_tokens: 1000
}));
```

工具名以当时实际发现的名字为准。每次触发只发送一次。结果不确定先查已发送邮件，不自动重发。已发送提示告知用户；明确重发才另行处理。不得篡改日期绕过校验。连接不可用保留成品并报告尚未发送。
