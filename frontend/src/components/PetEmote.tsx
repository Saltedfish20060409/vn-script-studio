import type { CSSProperties } from "react";
import { PET_EMOTE_SVG } from "../lib/petEmoteSvg";
import type { PetEmote as PetEmoteName } from "../lib/petMachine";
import "./petEmote.css";

type Props = {
  name: Exclude<PetEmoteName, null>;
  style?: CSSProperties;
  className?: string;
};

/** 情绪符号：内联 SVG，动画由 petEmote.css 按内部 class 驱动（img 引用拿不到内部节点） */
export function PetEmote({ name, style, className }: Props) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 48 48"
      className={`pet-emote pet-emote-${name}${className ? ` ${className}` : ""}`}
      style={style}
      aria-hidden="true"
      dangerouslySetInnerHTML={{ __html: PET_EMOTE_SVG[name] }}
    />
  );
}
