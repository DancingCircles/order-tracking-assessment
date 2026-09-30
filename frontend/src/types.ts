export interface Shipment {
  id: string
  label: string
  carrier: string
  tracking_no: string
}

export interface OrderLine {
  sku: string
  name: string
  description: string
  quantity: unknown
  shipment_id: string
  rrp: string | null
  ex_gst_unit_price: string | null
  line_subtotal_ex_gst: string | null
  issues: string[]
}

export interface Order {
  order_no: string
  order_date: string
  status: string
  company: string
  customer: string
  phone: string
  email: string
  shipping: { address: string; postcode: string }
  items: OrderLine[]
  shipments: Shipment[]
  issues: string[]
  summary: { subtotal_ex_gst: string; gst: string; shipment_fee: string; total: string } | null
  shipping_estimate: {
    availability: 'estimated' | 'partial' | 'unavailable'
    method: string
    shipments: {
      id: string; label: string; carrier: string; availability: 'estimated' | 'unavailable'
      fee: string; reason: string | null; actual_weight_kg: string | null
      volumetric_weight_kg: string | null; chargeable_weight_kg: string | null
    }[]
  }
}

export interface TrackingResult extends Shipment {
  availability: 'available' | 'unavailable'
  status: string | null
  last_updated: string | null
  reason: string | null
  source: string
  events: { date: string | null; description: string; location: string; article_id?: string }[]
}

export interface TrackingState {
  loading: boolean
  results: TrackingResult[]
  error: string | null
}
