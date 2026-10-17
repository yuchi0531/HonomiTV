import { beforeEach, describe, expect, it, vi } from 'vitest';

import APIClient, { IErrorResponse, ISuccessResponse } from '@/services/APIClient';
import Captures from '@/services/Captures';


vi.mock('@/services/APIClient', () => ({
    default: {get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), showGenericError: vi.fn()},
}));
vi.mock('@/utils', () => ({
    default: {api_base_url: 'https://example.test/api'},
    // Captures はアップロードの同時実行数を制限するため Semaphore を静的初期化で生成する
    Semaphore: class {
        public acquire(): void {}
        public release(): void {}
    },
}));

// API クライアントのレスポンスは判別可能な Union なので、テストでも型を明示して組み立てる
const success = <T>(data: T): ISuccessResponse<T> =>
    ({type: 'success', status: 200, headers: {}, data});
const failure = (detail: string): IErrorResponse => ({
    type: 'error', status: 422, headers: {}, data: {detail}, error: {} as unknown as IErrorResponse['error'],
});

describe('キャプチャ API クライアント', () => {
    beforeEach(() => vi.clearAllMocks());

    it('一覧取得では未指定の検索キーワードをそのまま渡し、axios に除外させる', async () => {
        vi.mocked(APIClient.get).mockResolvedValue(success({total: 0, captures: []}));

        expect(await Captures.fetchCaptures()).toEqual({total: 0, captures: []});
        expect(APIClient.get).toHaveBeenCalledWith('/captures', {
            params: {order: 'desc', page: 1, search: undefined},
        });
    });

    it('一覧取得に失敗した場合は null を返し、汎用エラーを表示する', async () => {
        vi.mocked(APIClient.get).mockResolvedValue(failure('Unexpected error'));

        expect(await Captures.fetchCaptures('asc', 2, 'ニュース')).toBeNull();
        expect(APIClient.get).toHaveBeenCalledWith('/captures', {
            params: {order: 'asc', page: 2, search: 'ニュース'},
        });
        expect(APIClient.showGenericError).toHaveBeenCalledOnce();
    });

    it('画像 URL はファイル名をエスケープし、サムネイル指定をクエリに付ける', () => {
        expect(Captures.getCaptureImageURL('Capture_テスト #1.jpg'))
            .toBe('https://example.test/api/captures/Capture_%E3%83%86%E3%82%B9%E3%83%88%20%231.jpg');
        expect(Captures.getCaptureImageURL('Capture.jpg', true))
            .toBe('https://example.test/api/captures/Capture.jpg?thumbnail=true');
    });

    it('削除はファイル名をエスケープした URL へ DELETE を送る', async () => {
        vi.mocked(APIClient.delete).mockResolvedValue(success(undefined));

        expect(await Captures.deleteCapture('a b.jpg')).toBe(true);
        expect(APIClient.delete).toHaveBeenCalledWith('/captures/a%20b.jpg');
    });

    it('フォルダ一覧の 401 はエラー通知せず、静かに空扱いにする', async () => {
        const unauthorized: IErrorResponse = {
            type: 'error', status: 401, headers: {}, data: {detail: 'Not authenticated'},
            error: {} as unknown as IErrorResponse['error'],
        };
        vi.mocked(APIClient.get).mockResolvedValue(unauthorized);

        expect(await Captures.fetchFolders()).toBeNull();
        expect(APIClient.showGenericError).not.toHaveBeenCalled();
    });

    it('フォルダ内キャプチャの登録解除は DELETE の本文でファイル名リストを送る', async () => {
        vi.mocked(APIClient.delete).mockResolvedValue(success(undefined));

        expect(await Captures.removeCapturesFromFolder(7, ['a.jpg', 'b.jpg'])).toBe(true);
        expect(APIClient.delete).toHaveBeenCalledWith('/captures/folders/7/captures', {
            data: {filenames: ['a.jpg', 'b.jpg']},
        });
    });

    it('フォルダ作成は前後の空白を除去せず送信し、検証はサーバーに任せる', async () => {
        vi.mocked(APIClient.post).mockResolvedValue(success({
            id: 1, name: '推し', sort_order: 0, capture_count: 0,
            created_at: '2026-10-17T00:00:00Z', updated_at: '2026-10-17T00:00:00Z',
        }));

        const created = await Captures.createFolder('推し');
        expect(created?.name).toBe('推し');
        expect(APIClient.post).toHaveBeenCalledWith('/captures/folders', {name: '推し'});
    });

    it('フォルダ更新は指定されたフィールドだけを送る', async () => {
        vi.mocked(APIClient.put).mockResolvedValue(success({
            id: 3, name: '新しい名前', sort_order: 0, capture_count: 2,
            created_at: '2026-10-17T00:00:00Z', updated_at: '2026-10-17T00:00:00Z',
        }));

        expect((await Captures.updateFolder(3, {name: '新しい名前'}))?.capture_count).toBe(2);
        expect(APIClient.put).toHaveBeenCalledWith('/captures/folders/3', {name: '新しい名前'});
    });
});
