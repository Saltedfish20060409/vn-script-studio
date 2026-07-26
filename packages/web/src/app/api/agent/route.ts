import { NextRequest, NextResponse } from "next/server";
import { runAgent, type AgentRequest } from "@vnss/core";

export async function POST(req: NextRequest) {
  try {
    const body = (await req.json()) as AgentRequest;
    const result = await runAgent(
      {
        apiKey: body.apiKey || process.env.DEEPSEEK_API_KEY || "",
        baseUrl: body.apiBaseUrl || process.env.DEEPSEEK_BASE_URL,
        model: body.apiModel || process.env.DEEPSEEK_MODEL,
      },
      body
    );
    return NextResponse.json(result);
  } catch (err) {
    const message = err instanceof Error ? err.message : "未知错误";
    return NextResponse.json({ error: message }, { status: 400 });
  }
}
