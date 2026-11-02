import { describe, expect, it } from 'vitest';


describe('字幕のフォント設定', () => {

    /** 一覧にあるフォント */
    const preset_fonts = [
        'Windows TV Gothic', 'Windows TV MaruGothic', 'Windows TV FutoMaruGothic',
        'Hiragino TV Sans Rd S', 'TT-ShinMGo-regular', 'Rounded M+ 1m for ARIB',
        'BIZ UDGothic', 'Noto Sans JP', 'Yu Gothic', 'sans-serif',
    ];

    /** 任意入力の選択肢の値 */
    const CUSTOM_FONT_VALUE = '__custom__';

    /**
     * フォントの選択状態を求める (コンポーネントの getter と同じロジック)
     * @param current 保存されているフォント名
     * @returns 選択肢の値
     */
    const selectionOf = (current: string): string =>
        preset_fonts.includes(current) === true ? current : CUSTOM_FONT_VALUE;

    it('一覧にあるフォントはそのまま選択状態になる', () => {
        expect(selectionOf('Noto Sans JP')).toBe('Noto Sans JP');
        expect(selectionOf('sans-serif')).toBe('sans-serif');
    });

    it('一覧にないフォント名は任意入力として扱う', () => {
        // OS にインストールした任意のフォント名を保存できる
        expect(selectionOf('源ノ角ゴシック JP')).toBe(CUSTOM_FONT_VALUE);
        expect(selectionOf('My Custom Font')).toBe(CUSTOM_FONT_VALUE);
    });
});


describe('字幕の font-family 組み立て', () => {

    /**
     * 設定値から font-family を組み立てる (PlayerController と同じロジック)
     * @param font 設定されているフォント名
     * @returns CSS の font-family 文字列
     */
    const buildFontFamily = (font: string): string => {
        if (font === 'sans-serif') {
            return 'sans-serif';
        }
        // 游ゴシックは OS ごとに名前が違うため複数の候補を並べる
        if (font === 'Yu Gothic') {
            font = 'Yu Gothic Medium|Yu Gothic|YuGothic';
        }
        const families = font.split('|')
            .map((family) => family.replace(/["\\]/g, '').trim())
            .filter((family) => family !== '')
            .map((family) => `"${family}"`);
        return `${families.join(', ')}, "Rounded M+ 1m for ARIB", sans-serif`;
    };

    it('任意のフォント名をそのまま指定できる', () => {
        expect(buildFontFamily('源ノ角ゴシック JP'))
            .toBe('"源ノ角ゴシック JP", "Rounded M+ 1m for ARIB", sans-serif');
    });

    it('游ゴシックは OS ごとの候補をすべて並べる', () => {
        // Windows と Mac で名前が異なるため、3つの候補を順に試す
        expect(buildFontFamily('Yu Gothic'))
            .toBe('"Yu Gothic Medium", "Yu Gothic", "YuGothic", "Rounded M+ 1m for ARIB", sans-serif');
    });

    it('CSS を壊す引用符を除去する', () => {
        // 入力に引用符が含まれても font-family 全体が無効にならないようにする
        expect(buildFontFamily('Bad"Font')).toBe('"BadFont", "Rounded M+ 1m for ARIB", sans-serif');
        expect(buildFontFamily('Bad\\Font')).toBe('"BadFont", "Rounded M+ 1m for ARIB", sans-serif');
    });

    it('デフォルトのフォントはそのまま返す', () => {
        expect(buildFontFamily('sans-serif')).toBe('sans-serif');
    });
});
