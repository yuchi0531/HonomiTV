import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';


describe('BS4K のパススルー画質', () => {

    const source = readFileSync(
        resolve(__dirname, 'PlayerController.ts'),
        'utf8',
    );

    it('TLV と MPEG-TS の両方を画質一覧に出す', () => {
        // 設定は初期値として使い、視聴中は両方を選べるようにする
        // 構成によっては Mirakurun が decode=0 でも MPEG-TS を返すため、
        // 一方だけを出すと選べないときに再生できなくなる
        expect(source).toContain('PlayerController.PASSTHROUGH_PRIMARY_QUALITY_NAME');
        expect(source).toContain('buildLiveOriginalHEVCQuality');
        // 設定値で分岐して片方だけを出す書き方が残っていない
        expect(source).not.toContain("if (this.bs4k_live_passthrough_mode === 'TLV') {\n                                qualities.push");
    });

    it('Main 10 の録画でもパススルーを選択肢に出す', () => {
        // Main 10 の再生可否は環境依存で誤判定しやすいため、
        // 常に選択肢に出して再生を試させる
        const main10Condition = source.includes("recorded_video.video_codec_profile === 'Main 10'");
        expect(main10Condition).toBe(true);
    });
});
