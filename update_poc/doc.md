# Updating files via tinyssb

```
master feed
+------+----------+----------+...
| Head | mk_child | mk_child |
+------+----------+----------+...
            |          :
            |    node feed
            |    +------+----------+--------+...
            '--> | Head | is_child | node_1 |
                 +------+----------+--------+...
                       :
                       |    update feed
                       |    +------+----------+-------- +...
                       '--> | Head | is_child | mk_child|
                            +------+----------+-------- +...
                                                   |
 /-------------------------------------------------'
 |
 |    version control file_1
 |    +------+----------+--------+----------+...
 '--> | Head | is_child | vcfile | mk_child |
      +------+----------+--------+----------+...
                                      |
                                      |    emergency feed vc file_1
                                      |    +------+----------+--------+...
                                      '--> | Head | is_child | vcfile |
                                           +------+----------+--------+...
```

```
Packet type vcfile: payload

                         47B
      1B        <- - - - - - - - - >
+-------------+-----------+---------+
| var_int len | file_name | padding |
+-------------+-----------+---------+

```

This allows for a file name of maximum 47B.

Version control feeds can easily be managed, by maintaining a Python
dictionary:

```python
vc_dict = {
    file_name_1: (feed_1, emergency_feed_1),
    file_name_2: (file_2, emergency_feed_2),
    ...
}
```

Once an emergency feed is triggered, the information can easily be updated:
```python
new_emergency_feed = feed_manager.create_child_feed(old_emergency_feed)
new_emergency_feed.append_version_control(file_name)
vc_dict[file_name] = (old_emergency_feed, new_emergency_feed)
```
