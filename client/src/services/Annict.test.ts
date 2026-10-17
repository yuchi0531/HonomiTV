import { beforeEach, describe, expect, it, vi } from 'vitest';

import Annict from '@/services/Annict';
import APIClient, { IErrorResponse, ISuccessResponse } from '@/services/APIClient';


vi.mock('@/services/APIClient', () => ({
    default: {get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), showGenericError: vi.fn()},
}));
// 通知は Pinia のストアを経由するため、サービス単体のテストでは差し替える
vi.mock('@/message', () => ({
    default: {success: vi.fn(), info: vi.fn(), warning: vi.fn(), error: vi.fn(), show: vi.fn()},
}));

const success = <T>(data: T): ISuccessResponse<T> =>
    ({type: 'success', status: 200, headers: {}, data});
const failure = (detail: string, status = 422): IErrorResponse => ({
    type: 'error', status, headers: {}, data: {detail}, error: {} as unknown as IErrorResponse['error'],
});

describe('Annict API クライアント', () => {
    beforeEach(() => vi.clearAllMocks());

    it('連携時はトークンをそのまま送り、成功なら true を返す', async () => {
        vi.mocked(APIClient.post).mockResolvedValue(success(undefined));

        expect(await Annict.loginAccount({access_token: 'token-value'})).toBe(true);
        expect(APIClient.post).toHaveBeenCalledWith('/annict/auth', {access_token: 'token-value'});
    });

    it('無効なトークンは再発行を促し、汎用エラーは出さない', async () => {
        vi.mocked(APIClient.post).mockResolvedValue(failure('Annict access token is invalid'));

        expect(await Annict.loginAccount({access_token: 'bad'})).toBe(false);
        expect(APIClient.showGenericError).not.toHaveBeenCalled();
    });

    it('空のトークンは入力を促すメッセージにする', async () => {
        vi.mocked(APIClient.post).mockResolvedValue(failure('Annict access token is empty'));

        expect(await Annict.loginAccount({access_token: ' '})).toBe(false);
        expect(APIClient.showGenericError).not.toHaveBeenCalled();
    });

    it('それ以外の連携エラーは汎用エラーとして表示する', async () => {
        vi.mocked(APIClient.post).mockResolvedValue(failure('Failed to get Annict user information (Connection Timeout)', 503));

        expect(await Annict.loginAccount({access_token: 'token'})).toBe(false);
        expect(APIClient.showGenericError).toHaveBeenCalledOnce();
    });

    it('自動記録の設定は PUT で enabled を送る', async () => {
        vi.mocked(APIClient.put).mockResolvedValue(success(undefined));

        expect(await Annict.updateAutoRecord(true)).toBe(true);
        expect(APIClient.put).toHaveBeenCalledWith('/annict/auto-record', {enabled: true});

        expect(await Annict.updateAutoRecord(false)).toBe(true);
        expect(APIClient.put).toHaveBeenLastCalledWith('/annict/auto-record', {enabled: false});
    });

    it('自動記録の設定に失敗した場合は false を返し、汎用エラーを表示する', async () => {
        vi.mocked(APIClient.put).mockResolvedValue(failure('Not authenticated', 401));

        expect(await Annict.updateAutoRecord(true)).toBe(false);
        expect(APIClient.showGenericError).toHaveBeenCalledOnce();
    });

    it('連携解除は DELETE を送る', async () => {
        vi.mocked(APIClient.delete).mockResolvedValue(success(undefined));

        expect(await Annict.logoutAccount()).toBe(true);
        expect(APIClient.delete).toHaveBeenCalledWith('/annict/logout');
    });
});
