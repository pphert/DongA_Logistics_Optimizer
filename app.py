import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from ortools.constraint_solver import routing_enums_pb2, pywrapcp
import math

st.set_page_config(page_title="Dong A Logistics Optimizer", layout="wide")

st.title("🚛 Hệ thống Tối ưu Tuyến đường & Kiểm soát Chi phí")
st.caption("Công nghệ: Google OR-Tools AI | Hỗ trợ tính toán hiệu quả Tài chính - Kế toán cho đội xe")

# --- HÀM TÍNH KHOẢNG CÁCH ---
def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def create_distance_matrix(df):
    num_nodes = len(df)
    matrix = []
    for i in range(num_nodes):
        row = []
        for j in range(num_nodes):
            if i == j:
                row.append(0)
            else:
                dist = haversine_distance(df.iloc[i]['Lat'], df.iloc[i]['Lon'], df.iloc[j]['Lat'], df.iloc[j]['Lon'])
                cost = int(dist * 1000)
                
                # Cấm đi từ điểm Lấy hàng (Pickup) sang điểm Giao hàng (Delivery)
                if df.iloc[i]['Type'] == 'Pickup' and df.iloc[j]['Type'] == 'Delivery':
                    cost = 9999999 
                    
                row.append(cost)
        matrix.append(row)
    return matrix

# --- BẢNG ĐIỀU KHIỂN BÊN TRÁI ---
st.sidebar.header("⚙️ 1. Cấu hình Đội xe")

if "fleet_size" not in st.session_state:
    st.session_state.fleet_size = 6

num_vehicles = st.sidebar.number_input("Số lượng xe điều phối:", min_value=1, step=1, value=st.session_state.fleet_size)

if "vehicle_df" not in st.session_state or st.session_state.fleet_size != num_vehicles:
    st.session_state.fleet_size = num_vehicles
    st.session_state.vehicle_df = pd.DataFrame({
        "Biển số xe": [f"51C-{12340 + i}" for i in range(num_vehicles)],
        "Tải trọng (Tấn)": [30] * num_vehicles
    })

edited_vehicles = st.sidebar.data_editor(st.session_state.vehicle_df, use_container_width=True, hide_index=False)
st.session_state.vehicle_df = edited_vehicles

vehicle_names = edited_vehicles["Biển số xe"].astype(str).tolist()
vehicle_capacities = edited_vehicles["Tải trọng (Tấn)"].astype(int).tolist()

st.sidebar.markdown("---")
st.sidebar.header("💰 2. Cấu hình Chi phí (VNĐ)")
fuel_cost_per_km = st.sidebar.number_input("Biến phí nhiên liệu (VNĐ/km):", min_value=0, value=5000, step=500)
fixed_vehicle_cost = st.sidebar.number_input("Định phí xuất xe (VNĐ/chuyến):", min_value=0, value=500000, step=50000)
max_acceptable_cost = st.sidebar.number_input("Mức tối đa chi phí chấp nhận:", min_value=0, value=3000000, step=100000)


# --- PHẦN 1: QUẢN LÝ DỮ LIỆU ĐƠN HÀNG ---
st.subheader("1. Dữ liệu Đơn hàng & Tọa độ")

if "orders_df" not in st.session_state:
    st.session_state.orders_df = pd.DataFrame({
        "NodeID": [0, 1, 2, 3, 4, 5, 6, 7],
        "Name": ["Kho Trung Tam Dong A", "KCN Tan Binh", "KCN Vinh Loc", "KCN Le Minh Xuan", "KCN Tan Tao", "KCN Hiep Phuoc", "KCN Cat Lai", "KCN Song Than"],
        "Type": ["Depot", "Delivery", "Delivery", "Delivery", "Delivery", "Pickup", "Pickup", "Pickup"],
        "Demand": [0, 15, 20, 15, 25, 20, 25, 15],
        "Lat": [10.8231, 10.8122, 10.8354, 10.7412, 10.7485, 10.6452, 10.7681, 10.9015],
        "Lon": [106.6297, 106.6201, 106.5752, 106.5284, 106.5821, 106.7451, 106.7865, 106.7482]
    })

edited_df = st.data_editor(
    st.session_state.orders_df, num_rows="dynamic", use_container_width=True,
    column_config={
        "Type": st.column_config.SelectboxColumn("Loại điểm", options=["Depot", "Delivery", "Pickup"], required=True),
        "Demand": st.column_config.NumberColumn("Demand (Tấn)"),
        "Lat": st.column_config.NumberColumn("Vĩ độ", format="%.6f"),
        "Lon": st.column_config.NumberColumn("Kinh độ", format="%.6f"),
    }
)
st.session_state.orders_df = edited_df
df = edited_df.dropna(subset=['Lat', 'Lon', 'Type']).reset_index(drop=True)

# --- DỰ TOÁN CHI PHÍ TRƯỚC TỐI ƯU ---
st.subheader("2. Phân tích & Tối ưu hóa")

if len(df) >= 2:
    depot_row = df[df['Type'] == 'Depot'].iloc[0]
    depot_lat, depot_lon = depot_row['Lat'], depot_row['Lon']
    
    manual_distance = 0
    manual_vehicles = 0
    
    # Tính toán nếu chạy thủ công: 1 xe chở 1 đơn rồi chạy rỗng về kho
    for i, row in df.iterrows():
        if row['Type'] != 'Depot':
            dist = haversine_distance(depot_lat, depot_lon, row['Lat'], row['Lon'])
            manual_distance += dist * 2  # Chặng đi + Chặng về rỗng
            manual_vehicles += 1
            
    manual_cost = (manual_vehicles * fixed_vehicle_cost) + (manual_distance * fuel_cost_per_km)

    st.info(f"📊 **DỰ TOÁN TRƯỚC TỐI ƯU (Vận hành thủ công):** Cần điều động **{manual_vehicles} xe** | Tổng quãng đường: **{manual_distance:.1f} km** | Tổng chi phí ước tính: **{manual_cost:,.0f} VNĐ**")

if st.button("🚀 Chạy Tối Ưu Hóa (OR-Tools Solver)"):
    if len(df) < 2:
        st.warning("Cần ít nhất 2 điểm để chạy.")
    else:
        with st.spinner("Hệ thống AI đang tính toán tổ hợp và phân tích tài chính..."):
            distance_matrix = create_distance_matrix(df)
            
            deliveries = [row['Demand'] if row['Type'] == 'Delivery' else 0 for _, row in df.iterrows()]
            pickups = [abs(row['Demand']) if row['Type'] == 'Pickup' else 0 for _, row in df.iterrows()]
            
            manager = pywrapcp.RoutingIndexManager(len(distance_matrix), num_vehicles, 0)
            routing = pywrapcp.RoutingModel(manager)

            def distance_callback(from_index, to_index):
                return distance_matrix[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]

            transit_callback_index = routing.RegisterTransitCallback(distance_callback)
            routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

            # Ép hệ thống dùng ít xe nhất có thể bằng phí phạt giả định
            routing.SetFixedCostOfAllVehicles(100000)

            def delivery_callback(from_index):
                return deliveries[manager.IndexToNode(from_index)]
            delivery_callback_index = routing.RegisterUnaryTransitCallback(delivery_callback)
            routing.AddDimensionWithVehicleCapacity(delivery_callback_index, 0, vehicle_capacities, True, 'Delivery_Capacity')

            def pickup_callback(from_index):
                return pickups[manager.IndexToNode(from_index)]
            pickup_callback_index = routing.RegisterUnaryTransitCallback(pickup_callback)
            routing.AddDimensionWithVehicleCapacity(pickup_callback_index, 0, vehicle_capacities, True, 'Pickup_Capacity')

            search_parameters = pywrapcp.DefaultRoutingSearchParameters()
            search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
            search_parameters.time_limit.seconds = 5 

            solution = routing.SolveWithParameters(search_parameters)

            if solution:
                total_distance = 0
                routes = []
                colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b']

                m = folium.Map(location=[depot_lat, depot_lon], zoom_start=11)

                for i, row in df.iterrows():
                    color = "black" if row['Type'] == 'Depot' else ("red" if row['Type'] == 'Delivery' else "green")
                    icon_type = "home" if row['Type'] == 'Depot' else ("arrow-up" if row['Type'] == 'Delivery' else "arrow-down")
                    folium.Marker(
                        [row['Lat'], row['Lon']],
                        popup=f"{row['Name']} ({row['Type']}) - Tải: {row['Demand']}T",
                        tooltip=row['Name'],
                        icon=folium.Icon(color=color, icon=icon_type, prefix='fa')
                    ).add_to(m)

                for vehicle_id in range(num_vehicles):
                    index = routing.Start(vehicle_id)
                    route_coords = []
                    route_nodes = []
                    route_distance = 0
                    route_del_load = 0
                    route_pic_load = 0
                    
                    while not routing.IsEnd(index):
                        node_index = manager.IndexToNode(index)
                        route_nodes.append(str(df.iloc[node_index]['Name']))
                        route_coords.append([df.iloc[node_index]['Lat'], df.iloc[node_index]['Lon']])
                        
                        route_del_load += deliveries[node_index]
                        route_pic_load += pickups[node_index]
                        
                        previous_index = index
                        index = solution.Value(routing.NextVar(index))
                        route_distance += routing.GetArcCostForVehicle(previous_index, index, vehicle_id)

                    node_index = manager.IndexToNode(index)
                    route_nodes.append(str(df.iloc[node_index]['Name']))
                    route_coords.append([df.iloc[node_index]['Lat'], df.iloc[node_index]['Lon']])
                    
                    actual_distance = (route_distance - 100000) / 1000 if route_distance > 100000 else 0

                    if len(route_nodes) > 2:
                        total_distance += actual_distance
                        folium.PolyLine(
                            route_coords, color=colors[vehicle_id % len(colors)], weight=5, opacity=0.8,
                            tooltip=f"Lộ trình {vehicle_names[vehicle_id]}"
                        ).add_to(m)
                        
                        routes.append({
                            "Biển số": vehicle_names[vehicle_id],
                            "Tải Max": f"{vehicle_capacities[vehicle_id]} T",
                            "Giao đi": f"{route_del_load} T",
                            "Lấy về": f"{route_pic_load} T",
                            "Quãng đường": f"{round(actual_distance, 2)} km",
                            "Lộ trình": " ➔ ".join(route_nodes)
                        })

                # --- TÍNH TOÁN TÀI CHÍNH SAU TỐI ƯU ---
                vehicles_used = len(routes)
                optimized_cost = (vehicles_used * fixed_vehicle_cost) + (total_distance * fuel_cost_per_km)
                savings = manual_cost - optimized_cost
                
                # --- KIỂM TRA NGÂN SÁCH CHẤP NHẬN ---
                if optimized_cost <= max_acceptable_cost:
                    st.success(f"✅ **ĐẠT CHỈ TIÊU CHI PHÍ:** Hệ thống hoạt động dưới mức ngân sách tối đa ({max_acceptable_cost:,.0f} VNĐ).")
                else:
                    st.error(f"⚠️ **CẢNH BÁO NGÂN SÁCH:** Chi phí tối ưu ({optimized_cost:,.0f} VNĐ) đang VƯỢT ngân sách cho phép. Hãy cân nhắc từ chối bớt đơn lấy hàng hoặc thay đổi trọng tải xe.")

                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Tổng chi phí Tối ưu", f"{optimized_cost:,.0f} đ", f"-{savings:,.0f} đ", delta_color="inverse")
                col2.metric("Số xe thực tế sử dụng", f"{vehicles_used} / {num_vehicles} xe", f"-{manual_vehicles - vehicles_used} xe rỗng")
                col3.metric("Tổng quãng đường", f"{round(total_distance, 2)} km", f"-{round(manual_distance - total_distance, 1)} km")
                col4.metric("Đơn lấy hàng (Backhaul)", f"{len(df[df['Type'] == 'Pickup'])} đơn ghép")

                st.subheader("Bản đồ điều phối trực quan")
                st_folium(m, width=1000, height=520, returned_objects=[])

                st.subheader("Chi tiết Lộ trình điều động")
                st.table(pd.DataFrame(routes))
            else:
                st.error("❌ Không tìm thấy phương án tối ưu!")