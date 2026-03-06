import { Asset, AssetTheme, EditorSettings } from '../types';

export const DB_NAME = 'DV3EditorDB';
export const DB_VERSION = 1;
export const STORE_ASSETS = 'assets';
export const STORE_SETTINGS = 'settings';
export const SETTINGS_KEY = 'user_settings';

export const initDB = (): Promise<IDBDatabase> => {
  return new Promise((resolve, reject) => {
    try {
      const request = indexedDB.open(DB_NAME, DB_VERSION);

      request.onupgradeneeded = (e) => {
        const db = (e.target as IDBOpenDBRequest).result;
        if (!db.objectStoreNames.contains(STORE_ASSETS)) {
          db.createObjectStore(STORE_ASSETS, { keyPath: 'id' });
        }
        if (!db.objectStoreNames.contains(STORE_SETTINGS)) {
          db.createObjectStore(STORE_SETTINGS, { keyPath: 'id' });
        }
      };

      request.onsuccess = () => resolve(request.result);

      request.onerror = () => {
        console.error('IndexedDB init error:', request.error);
        reject(request.error);
      };
    } catch (err) {
      console.error('IndexedDB not supported or blocked', err);
      reject(err);
    }
  });
};

export const saveAssetToDB = async (asset: Asset): Promise<boolean> => {
  try {
    const db = await initDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_ASSETS, 'readwrite');

      // Don't save the transient fileUrl to DB
      const assetToSave: Omit<Asset, 'fileUrl'> = {
        id: asset.id,
        originalFile: asset.originalFile,
        name: asset.name,
        type: asset.type,
        emotion: asset.emotion,
        additionalEmotions: asset.additionalEmotions ?? [],
        context: asset.context,
        theme: asset.theme ?? 'dark',
        title: asset.title,
        notes: asset.notes,
        editStack: asset.editStack,
        historyIndex: asset.historyIndex,
        linkedVariantId: asset.linkedVariantId,
        lastExportedAt: asset.lastExportedAt,
      };

      tx.objectStore(STORE_ASSETS).put(assetToSave);
      tx.oncomplete = () => resolve(true);
      tx.onerror = () => reject(tx.error);
    });
  } catch (err) {
    console.warn('Failed to save asset to DB. Storage might be full or disabled.', err);
    return false;
  }
};

export const loadAssetsFromDB = async (): Promise<Asset[]> => {
  try {
    const db = await initDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_ASSETS, 'readonly');
      const request = tx.objectStore(STORE_ASSETS).getAll();
      request.onsuccess = () => {
        const results = request.result;
        // Recreate object URLs for loaded files
        const hydrated = results.map((item: Omit<Asset, 'fileUrl'>) => ({
          ...item,
          // Migrate legacy assets missing new fields
          additionalEmotions: (item as { additionalEmotions?: string[] }).additionalEmotions ?? [],
          theme: ((item as { theme?: AssetTheme }).theme ?? 'dark') as AssetTheme,
          fileUrl: URL.createObjectURL(item.originalFile)
        }));
        resolve(hydrated);
      };
      request.onerror = () => reject(request.error);
    });
  } catch (err) {
    console.warn('Failed to load assets from DB.', err);
    return [];
  }
};

export const deleteAssetFromDB = async (id: string): Promise<boolean> => {
  try {
    const db = await initDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_ASSETS, 'readwrite');
      tx.objectStore(STORE_ASSETS).delete(id);
      tx.oncomplete = () => resolve(true);
      tx.onerror = () => reject(tx.error);
    });
  } catch (err) {
    console.warn('Failed to delete asset from DB.', err);
    return false;
  }
};

export const saveSettingsToDB = async (settings: EditorSettings): Promise<boolean> => {
  try {
    const db = await initDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_SETTINGS, 'readwrite');
      tx.objectStore(STORE_SETTINGS).put({ id: SETTINGS_KEY, ...settings });
      tx.oncomplete = () => resolve(true);
      tx.onerror = () => reject(tx.error);
    });
  } catch (err) {
    console.warn('Failed to save settings to DB.', err);
    return false;
  }
};

export const loadSettingsFromDB = async (): Promise<EditorSettings | null> => {
  try {
    const db = await initDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_SETTINGS, 'readonly');
      const request = tx.objectStore(STORE_SETTINGS).get(SETTINGS_KEY);
      request.onsuccess = () => {
        if (request.result) {
          const raw = request.result as { id: string } & EditorSettings;
          resolve({
            exportRoot: raw.exportRoot,
            defaultPadding: raw.defaultPadding,
          });
        } else {
          resolve(null);
        }
      };
      request.onerror = () => reject(request.error);
    });
  } catch (err) {
    console.warn('Failed to load settings from DB.', err);
    return null;
  }
};
