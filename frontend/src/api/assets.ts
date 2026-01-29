import api from '@/api/client'
import type { Asset, AssetCreate, AssetUpdate } from '@/types/asset'

// Re-export types for convenience
export type { Asset, AssetCreate, AssetUpdate } from '@/types/asset'

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export async function getAssets(
  novelId: string,
  params?: {
    asset_type?: string
    is_global?: boolean
    page?: number
    page_size?: number
  }
): Promise<PaginatedResponse<Asset>> {
  const response = await api.get(`/novels/${novelId}/assets`, { params })
  return response.data
}

export async function getAsset(novelId: string, assetId: string): Promise<Asset> {
  const response = await api.get(`/novels/${novelId}/assets/${assetId}`)
  return response.data
}

export async function createAsset(novelId: string, data: AssetCreate): Promise<Asset> {
  const response = await api.post(`/novels/${novelId}/assets`, data)
  return response.data
}

export async function updateAsset(
  novelId: string,
  assetId: string,
  data: AssetUpdate
): Promise<Asset> {
  const response = await api.put(`/novels/${novelId}/assets/${assetId}`, data)
  return response.data
}

export async function deleteAsset(novelId: string, assetId: string): Promise<void> {
  await api.delete(`/novels/${novelId}/assets/${assetId}`)
}

export async function getAssetsByType(
  novelId: string,
  assetType: string
): Promise<Asset[]> {
  const response = await api.get(`/novels/${novelId}/assets/by-type/${assetType}`)
  return response.data
}

export async function getGlobalAssets(
  novelId: string,
  assetType?: string
): Promise<Asset[]> {
  const response = await api.get(`/novels/${novelId}/assets/global`, {
    params: { asset_type: assetType },
  })
  return response.data
}

export async function mergeAssets(
  novelId: string,
  sourceId: string,
  targetId: string
): Promise<Asset> {
  const response = await api.post(
    `/novels/${novelId}/assets/${sourceId}/merge/${targetId}`
  )
  return response.data
}

export async function uploadAssetImage(
  novelId: string,
  assetId: string,
  file: File,
  imageField: 'main_image' | 'angle_image_1' | 'angle_image_2' = 'main_image'
): Promise<Asset> {
  const formData = new FormData()
  formData.append('file', file)

  const response = await api.post(
    `/novels/${novelId}/assets/${assetId}/upload-image`,
    formData,
    {
      params: { image_field: imageField },
      headers: { 'Content-Type': 'multipart/form-data' },
    }
  )
  return response.data
}

export async function generateAssetImage(
  novelId: string,
  assetId: string,
  imageField: 'main_image' | 'angle_image_1' | 'angle_image_2' = 'main_image'
): Promise<Asset> {
  const response = await api.post(
    `/novels/${novelId}/assets/${assetId}/generate-image`,
    null,
    { params: { image_field: imageField } }
  )
  return response.data
}
