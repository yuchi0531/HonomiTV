import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it } from 'vitest';

import { IRecordedProgramDefault } from '@/services/Videos';
import { ProgramUtils } from '@/utils/ProgramUtils';


// 前後の CM をカットした録画を模した番組を作る
// 放送は 30 分 (12:00:00 ～ 12:30:00) だが、録画ファイルは 24 分しかない
const buildTrimmedProgram = () => ({
    ...IRecordedProgramDefault,
    start_time: '2026-10-17T12:00:00+09:00',
    end_time: '2026-10-17T12:30:00+09:00',
    duration: 1800,
    recorded_video: {
        ...IRecordedProgramDefault.recorded_video,
        // ファイルの実時間は CM カットで短くなっている
        recording_start_time: '2026-10-17T12:02:00+09:00',
        recording_end_time: '2026-10-17T12:26:00+09:00',
        duration: 1440,
    },
});

describe('録画番組の放送時間表示', () => {
    // ProgramUtils は設定ストアを参照するため、各テストで Pinia を有効にする
    beforeEach(() => setActivePinia(createPinia()));

    it('放送時間を表示し、CM カット後のファイル時間を使わない', () => {
        const text = ProgramUtils.getRecordingTime(buildTrimmedProgram());

        // EPG 上の放送時間 (12:00 ～ 12:30) が出る
        expect(text).toContain('12:00:00');
        expect(text).toContain('12:30:00');
        // 番組長も放送時間の 30 分になる (ファイルの 24 分ではない)
        expect(text).toContain('(30分)');
        // 録画ファイルの実時間は出さない
        expect(text).not.toContain('12:02:00');
        expect(text).not.toContain('12:26:00');
    });

    it('放送時間とファイル時間が同じ場合は従来どおりの表示になる', () => {
        const program = {
            ...buildTrimmedProgram(),
            recorded_video: {
                ...buildTrimmedProgram().recorded_video,
                recording_start_time: '2026-10-17T12:00:00+09:00',
                recording_end_time: '2026-10-17T12:30:00+09:00',
                duration: 1800,
            },
        };

        const text = ProgramUtils.getRecordingTime(program);

        expect(text).toContain('12:00:00');
        expect(text).toContain('12:30:00');
        expect(text).toContain('(30分)');
    });

    it('録画マージンで放送時間より長く録画した場合も放送時間を表示する', () => {
        const program = {
            ...buildTrimmedProgram(),
            recorded_video: {
                ...buildTrimmedProgram().recorded_video,
                // 開始 5 秒前から終了 2 秒後まで録画している
                recording_start_time: '2026-10-17T11:59:55+09:00',
                recording_end_time: '2026-10-17T12:30:02+09:00',
                duration: 1807,
            },
        };

        const text = ProgramUtils.getRecordingTime(program);

        expect(text).toContain('12:00:00');
        expect(text).toContain('12:30:00');
        expect(text).toContain('(30分)');
    });

    it('放送時刻は EPG を使い、録画マージンやファイル時間を混ぜない', () => {
        // 録画は 11:59:55 から始まり、CM カットで実ファイルは 24 分しかない
        const program = {
            ...buildTrimmedProgram(),
            recorded_video: {
                ...buildTrimmedProgram().recorded_video,
                recording_start_time: '2026-10-17T11:59:55+09:00',
                recording_end_time: '2026-10-17T12:26:00+09:00',
                duration: 1440,
            },
        };

        const text = ProgramUtils.getProgramTime(program);

        // EPG 上の放送時刻 (12:00 ～ 12:30) と番組長 (30分) が出る
        expect(text).toContain('12:00');
        expect(text).toContain('12:30');
        expect(text).toContain('(30分)');
        // 録画マージンの開始時刻や CM カット後の長さは出さない
        expect(text).not.toContain('11:59');
        expect(text).not.toContain('(24分)');
    });

    it('短縮表記でも EPG の放送時刻を使う', () => {
        const text = ProgramUtils.getProgramTime(buildTrimmedProgram(), true);

        expect(text).toBe('2026/10/17 12:00 ～ 12:30');
    });
});
