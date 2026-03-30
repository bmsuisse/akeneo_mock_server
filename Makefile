.PHONY: run run-listener run-worker run-all test test-erp test-etl e2e trigger-event seed format typecheck check

run:
	uv run uvicorn akeneo_mock_server.app:app --reload --reload-dir . --reload-exclude "tests" --reload-exclude "scripts"

test:
	uv run pytest tests/test_api.py tests/test_crud.py -v

format:
	uv run ruff format .

typecheck:
	uv run pyright akeneo_mock_server tests/test_api.py

seed:
	uv run python seed_data.py

test-contract:
	uv run pytest tests/test_contract.py -v

check: format typecheck test test-contract

update-api-docs:
	cd pim-api-docs && git restore . && git checkout master && git pull origin master
	uv run python patch_schema.py
	$(MAKE) test-contract


# Trigger a product-changed event end-to-end:
#   Creates/updates a product in the Akeneo mock with realistic field values.
# Usage: make trigger-event PRODUCT=MY-ARTICLE
PRODUCT ?= E2E-DEMO-001
LISTENER_URL ?= http://localhost:8001

trigger-event:
	@echo "Registering listener subscriber …"
	@curl -sf -X POST http://localhost:8000/api/v1/subscribers \
		-H 'Content-Type: application/json' \
		-d '{"id":"erp-listener","url":"$(LISTENER_URL)/webhook"}' || true
	@curl -sf -X POST http://localhost:8000/api/v1/subscribers/erp-listener/subscriptions \
		-H 'Content-Type: application/json' \
		-d '{"id":"product-events","events":["akeneo.pim.v1.product.updated","akeneo.pim.v1.product.created"]}' || true
	@echo "Triggering product change for $(PRODUCT) …"
	@uv run python -c "\
import httpx, json; \
payload = { \
  'identifier': '$(PRODUCT)', \
  'family': 'flooring', \
  'values': { \
    'description':              [{'locale':None,'scope':None,'data':'$(PRODUCT) — Product via make trigger-event'}], \
    'commercial_description':   [{'locale':None,'scope':None,'data':'Commercial description for $(PRODUCT)'}], \
    'gtin':                     [{'locale':None,'scope':None,'data':'4006975012345'}], \
    'discount_group':           [{'locale':None,'scope':None,'data':'FLOOR-A'}], \
    'price_group':              [{'locale':None,'scope':None,'data':'PG-01'}], \
    'availability':             [{'locale':None,'scope':None,'data':'10'}], \
    'vendor':                   [{'locale':None,'scope':None,'data':'VENDOR-OAK-001'}], \
    'freight_code':             [{'locale':None,'scope':None,'data':'FRACHT-A'}], \
    'company_name':             [{'locale':None,'scope':None,'data':'BMS Europe'}], \
    'item_vendor':              [{'locale':None,'scope':None,'data':'OAK-12345'}], \
    'stock_unit_of_measurement':[{'locale':None,'scope':None,'data':'m2'}], \
    'package_unit_of_measurement':[{'locale':None,'scope':None,'data':'PAK'}], \
    'price_unit_of_measurement':[{'locale':None,'scope':None,'data':'m2'}], \
    'packaging':                [{'locale':None,'scope':None,'data':2}], \
    'next_unit_pack':           [{'locale':None,'scope':None,'data':10}], \
    'pallet':                   [{'locale':None,'scope':None,'data':'EUR-1'}], \
    'weight':                   [{'locale':None,'scope':None,'data':8.5}], \
    'volume':                   [{'locale':None,'scope':None,'data':0.018}], \
    'length':                   [{'locale':None,'scope':None,'data':1.2}], \
    'area':                     [{'locale':None,'scope':None,'data':2.0}], \
    'shoulder_length':          [{'locale':None,'scope':None,'data':15}], \
    'width':                    [{'locale':None,'scope':None,'data':120}], \
    'factor':                   [{'locale':None,'scope':None,'data':1.0}], \
    'pallet_price':             [{'locale':None,'scope':None,'data':485.0}], \
    'pallet_factor':            [{'locale':None,'scope':None,'data':40.0}], \
    'own_brand':                [{'locale':None,'scope':None,'data':'OAK-PREMIUM'}], \
    'freeze_class':             [{'locale':None,'scope':None,'data':'F0'}], \
    'abrasion_class':           [{'locale':None,'scope':None,'data':'AC4'}], \
    'en_class':                 [{'locale':None,'scope':None,'data':'EN13489'}], \
    'slip_resistance':          [{'locale':None,'scope':None,'data':'R10'}], \
    'series_name':              [{'locale':None,'scope':None,'data':'Heritage'}], \
    'promotion':                [{'locale':None,'scope':None,'data':'SPRING2026'}], \
    'shelf_life_months':        [{'locale':None,'scope':None,'data':240}], \
    'end_of_life_date':         [{'locale':None,'scope':None,'data':'2040-12-31'}], \
    'created_by':               [{'locale':None,'scope':None,'data':'MAKE'}], \
    'changed_by':               [{'locale':None,'scope':None,'data':'MAKE'}], \
    'base_stock_item':          [{'locale':None,'scope':None,'data':True}], \
    'general_item':             [{'locale':None,'scope':None,'data':True}], \
    'display_on_orders':        [{'locale':None,'scope':None,'data':True}], \
    'display_on_sales_quote':   [{'locale':None,'scope':None,'data':True}], \
    'record_ok':                [{'locale':None,'scope':None,'data':True}], \
    'country_origin_required':  [{'locale':None,'scope':None,'data':True}], \
    'lot_no':                   [{'locale':None,'scope':None,'data':False}], \
    'service_item':             [{'locale':None,'scope':None,'data':False}], \
  } \
}; \
r = httpx.patch('http://localhost:8000/api/rest/v1/products/$(PRODUCT)', json=payload); \
print('Status:', r.status_code)"
	@echo "\nDone — check queue size: curl http://localhost:8001/queue/size"
