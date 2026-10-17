import Message from '@/message';
import APIClient from '@/services/APIClient';


/** Annict アカウントと個人用アクセストークンで連携するためのリクエストを表すインターフェイス */
export interface IAnnictAuthRequest {
    access_token: string;
}

class Annict {

    /**
     * Annict アカウントと個人用アクセストークンで連携する
     * @param auth_request Annict 個人用アクセストークン
     * @returns 連携に成功した場合は true、失敗した場合は false
     */
    static async loginAccount(auth_request: IAnnictAuthRequest): Promise<boolean> {

        // API リクエストを実行
        const response = await APIClient.post('/annict/auth', auth_request);

        // 無効な個人用アクセストークンは、再発行が必要なことを明示する
        if (response.type === 'error') {
            if (response.data.detail === 'Annict access token is invalid') {
                Message.error('Annict の個人用アクセストークンが無効です。');
                return false;
            }
            if (response.data.detail === 'Annict access token is empty') {
                Message.error('Annict の個人用アクセストークンを入力してください。');
                return false;
            }
            APIClient.showGenericError(response, 'Annict アカウントとの連携に失敗しました。');
            return false;
        }

        return true;
    }


    /**
     * 視聴記録の自動投稿のオン・オフを保存する
     * @param enabled 自動投稿する場合は true
     * @returns 保存に成功した場合は true、失敗した場合は false
     */
    static async updateAutoRecord(enabled: boolean): Promise<boolean> {

        // API リクエストを実行
        const response = await APIClient.put('/annict/auto-record', {enabled});

        // エラー処理
        if (response.type === 'error') {
            APIClient.showGenericError(response, 'Annict の自動記録設定を更新できませんでした。');
            return false;
        }

        return true;
    }


    /**
     * 現在ログイン中のユーザーアカウントに紐づく Annict アカウントとの連携を解除する
     * @returns 連携解除に成功した場合は true、失敗した場合は false
     */
    static async logoutAccount(): Promise<boolean> {

        // API リクエストを実行
        const response = await APIClient.delete('/annict/logout');

        // エラー処理
        if (response.type === 'error') {
            APIClient.showGenericError(response, 'Annict アカウントとの連携を解除できませんでした。');
            return false;
        }

        return true;
    }
}

export default Annict;
