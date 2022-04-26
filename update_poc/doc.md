# Updating files via tinyssb


```
master feed
+------+-----------+---------------+
| Head | node_fids | update_master | ..+
+------+-----------+---------------+
```

In order to get the update_master feed:
```python
update_master = master_feed.get_children()[1]
```

This update master feed contains one child feed for every monitored file.
