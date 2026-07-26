import { NextRequest, NextResponse } from "next/server";
import { runAi, type AiRequest } from "@vnss/core";

export async function POST(req: NextRequest) {
  try {
    const body = (await req.json()) as AiRequest;
    const apiKey = process.env.DEEPSEEK_API_KEY ?? "";
    const result = await runAi(
      {
        apiKey,
        baseUrl: process.env.DEEPSEEK_BASE_URL,
        model: process.env.DEEPSEEK_MODEL,
      },
      body
    );
    return NextResponse.json(result);
  } catch (err) {
    const message = err instanceof Error ? err.message : "未知错误";
    return NextResponse.json({ error: message }, { status: 400 });
  }
}
