import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';


describe('シリーズのパンくずリスト', () => {

    /**
     * 画面ファイルのソースを返す
     * @param name ファイル名
     * @returns ソースコード
     */
    const sourceOf = (name: string): string =>
        readFileSync(resolve(__dirname, name), 'utf8');

    /**
     * ソースからパンくずの定義を取り出す
     * @param source ソースコード
     * @returns パンくずの name 一覧
     */
    const crumbNames = (source: string): string[] => {
        const block = source.match(/<Breadcrumbs :crumbs="\[([\s\S]*?)\]"/);
        if (block === null) {
            return [];
        }
        return [...block[1].matchAll(/name: '([^']+)'/g)].map((m) => m[1]);
    };

    it('放送中はシリーズの中にある階層で表示する', () => {
        // 放送中は独立した画面ではなく、シリーズの中の位置づけ
        expect(crumbNames(sourceOf('OnAir.vue'))).toEqual(['ホーム', 'シリーズ', '放送中']);
    });

    it('シリーズ一覧はホームの直下として表示する', () => {
        expect(crumbNames(sourceOf('Home.vue'))).toEqual(['ホーム', 'シリーズ']);
    });

    it('放送中への入口はスマートフォンだけに出す', () => {
        // PC ではパンくずとシリーズ一覧から辿れるため、専用のタブは不要
        const source = sourceOf('Home.vue');
        const button = source.match(/<v-btn[^>]*to="\/series\/on-air"[\s\S]*?<\/v-btn>/);
        expect(button).not.toBeNull();
        expect(button![0]).toContain('Utils.isSmartphoneVertical()');
    });
});
